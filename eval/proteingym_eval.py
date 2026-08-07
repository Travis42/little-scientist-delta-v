#!/usr/bin/env python3
"""ProteinGym eval for SEF validator.

Runs the agent's strategy on ALL proteins from the ProteinGym benchmark
(217 substitution datasets), computes Spearman correlation + speed bonus.
Outputs JSON score for the validator's accept/reject gate.

Usage: python3 proteingym_eval.py --dir <workspace_dir>
"""
import sys, os, json, time, importlib.util, traceback, random, gc
import numpy as np
from scipy.stats import spearmanr

# ── Configuration ──────────────────────────────────────────────────────────
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
# Make scripts/ importable so strategies can `import proteingym_data`
if EVAL_DIR not in sys.path:
    sys.path.insert(0, EVAL_DIR)
DATA_DIR = os.environ.get('PROTEINGYM_DATA',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'DMS_ProteinGym_substitutions'))
REFERENCE_FILE = os.environ.get('PROTEINGYM_REFERENCE',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'DMS_substitutions.csv'))
MSA_DIR = os.environ.get('PROTEINGYM_MSA',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'DMS_msa_files'))
# Canonical path to the integrated data DB. Strategies import proteingym_data,
# which reads PROTEINGYM_DB (defaulting to data/proteingym_data.db).
os.environ.setdefault(
    'PROTEINGYM_DB',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'proteingym_data.db'),
)

# All available ProteinGym substitution proteins (217 datasets)
# Dynamically discovered from the data directory
import glob as _glob
_EVAL_PROTEIN_FILES = sorted(_glob.glob(os.path.join(DATA_DIR, '*.csv')))
EVAL_PROTEINS = [os.path.splitext(os.path.basename(f))[0] for f in _EVAL_PROTEIN_FILES]

# Smoke test uses first 5 (deterministic order, same every run)
SMOKE_PROTEINS = EVAL_PROTEINS[:5]

# Load per-protein timeout from config
_TIMINGS_PATH = os.path.join(os.path.dirname(EVAL_DIR), "config", "timings.json")
try:
    with open(_TIMINGS_PATH) as _f:
        STRATEGY_TIMEOUT = json.load(_f).get("eval_per_protein_timeout_seconds", 300)
except Exception:
    STRATEGY_TIMEOUT = 300
SPEED_BONUS_MAX = 0.002
SPEED_INFLECTION_S = 10  # inflection point for speed bonus (tighter)

AMINO_ACIDS = 'ACDEFGHIKLMNPQRSTVWY'

# In-memory mutation cache (avoids re-reading CSV files)
_MUTATION_CACHE = {}

# AA property groups for substitution analysis
_AA_GROUPS = {
    'hydrophobic': 'AVLIMFWC',
    'positive': 'KRH',
    'negative': 'DE',
    'polar': 'STNQ',
    'special': 'GP',
    'aromatic': 'FYW',
}

def _aa_group(aa):
    for group, aas in _AA_GROUPS.items():
        if aa in aas:
            return group
    return 'other'

def _substitution_class(wt_aa, mut_aa):
    return f'{_aa_group(wt_aa)}→{_aa_group(mut_aa)}'

# ── Helpers ────────────────────────────────────────────────────────────────

def load_reference():
    """Load reference file with protein metadata."""
    import csv
    proteins = {}
    with open(REFERENCE_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            proteins[row['DMS_id']] = row
    return proteins

def load_mutations(protein_id, reference):
    """Load mutations CSV for a protein. Returns (mutations, scores, mutant_codes)."""
    dms_file = os.path.join(DATA_DIR, f'{protein_id}.csv')
    if not os.path.exists(dms_file):
        return None, None, None
    
    # Check cache
    if protein_id in _MUTATION_CACHE:
        return _MUTATION_CACHE[protein_id]
    
    import csv
    mutations = []
    scores = []
    mutant_codes = []
    with open(dms_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # ProteinGym format: 'mutant' column (e.g. "A10C") is what
            # model prediction DB expects. Use it as the primary mutation
            # identifier. 'mutated_sequence' is the full sequence (not
            # useful for DB lookups).
            if 'mutant' in row:
                mutations.append(row['mutant'])
            elif 'mutated_sequence' in row:
                mutations.append(row['mutated_sequence'])
            scores.append(float(row['DMS_score']))
            mutant_codes.append(row.get('mutant', ''))
    
    result = (mutations, scores, mutant_codes)
    _MUTATION_CACHE[protein_id] = result
    return result

# Assay type lookup (from reference CSV)
_ASSAY_CACHE = {}

def load_assay_type(protein_id, reference):
    """Get coarse selection type for a protein."""
    if protein_id in _ASSAY_CACHE:
        return _ASSAY_CACHE[protein_id]
    at = reference.get(protein_id, {}).get('coarse_selection_type', 'Unknown')
    if not at:
        at = 'Unknown'
    _ASSAY_CACHE[protein_id] = at
    return at

# Shannon entropy at each position from MSA
import math
from collections import Counter as _Counter

def compute_position_entropy(msa, protein_length):
    """Per-position Shannon entropy (bits) from MSA.
    Low = conserved. High = variable."""
    if not msa or protein_length == 0:
        return None
    entropy = []
    for pos in range(protein_length):
        col = [seq[pos] for seq in msa if pos < len(seq)]
        if not col:
            entropy.append(0.0)
            continue
        counts = _Counter(col)
        total = len(col)
        h = 0.0
        for aa, cnt in counts.items():
            p = cnt / total
            if p > 0:
                h -= p * math.log2(p)
        entropy.append(h)
    return entropy

_HYDROPHOBIC = set('AVLIMFWC')

def classify_position(entropy_val, wt_aa):
    """Proxy for structural burial: core (conserved+hydrophobic), surface, flexible."""
    if entropy_val < 2.0 and wt_aa in _HYDROPHOBIC:
        return 'core'
    elif entropy_val >= 3.0:
        return 'flexible'
    else:
        return 'surface'

MSA_SUBSAMPLE_SEED = 42
MSA_MIN_DEPTH = 500
MSA_DEPTH_FACTOR = 10  # sample_n = max(MSA_MIN_DEPTH, min(total, factor × protein_length))

def compute_msa_sample_n(total_seqs, protein_length):
    """Length-scaled MSA subsampling count.
    
    Formula: max(500, min(total_seqs, 10 × protein_length))
    
    Longer proteins need more sequences for stable frequency estimates.
    10× is empirically validated as the tightest factor with <0.001 Spearman
    delta vs 10K baseline across 8 diverse proteins.
    """
    return max(MSA_MIN_DEPTH, min(total_seqs, MSA_DEPTH_FACTOR * protein_length))

def load_msa(protein_id, reference, protein_length=None):
    """Load MSA for a protein, subsampled to a length-scaled cap.
    
    Uses reservoir sampling (deterministic via MSA_SUBSAMPLE_SEED) when the
    MSA exceeds the cap. This caps memory at ~5MB per protein instead of
    loading multi-hundred-MB files. Empirically validated: Spearman delta
    vs full MSA is <0.002 across proteins up to 1.9M sequences.
    """
    msa_filename = reference.get('MSA_filename', '').strip()
    if not msa_filename:
        return None
    
    msa_path = os.path.join(MSA_DIR, msa_filename)
    if not os.path.exists(msa_path):
        return None
    
    # First pass: count sequences
    total_seqs = 0
    with open(msa_path) as f:
        for line in f:
            if line.startswith('>'):
                total_seqs += 1
    
    # Determine sample size (length-scaled if protein_length provided)
    if protein_length and protein_length > 0:
        sample_n = compute_msa_sample_n(total_seqs, protein_length)
    else:
        sample_n = 10_000  # fallback
    
    if total_seqs <= sample_n:
        # Small enough — load directly
        seqs = []
        with open(msa_path) as f:
            seq = ''
            for line in f:
                if line.startswith('>'):
                    if seq:
                        seqs.append(seq)
                    seq = ''
                else:
                    seq += line.strip()
            if seq:
                seqs.append(seq)
        return seqs if seqs else None
    
    # Reservoir sample — deterministic subset of sample_n sequences
    rng = random.Random(MSA_SUBSAMPLE_SEED)
    keep_indices = set(rng.sample(range(total_seqs), sample_n))
    
    seqs = []
    idx = 0
    seq = ''
    in_keep = False
    with open(msa_path) as f:
        for line in f:
            if line.startswith('>'):
                if seq and in_keep:
                    seqs.append(seq)
                seq = ''
                in_keep = idx in keep_indices
                idx += 1
            else:
                if in_keep:
                    seq += line.strip()
        if seq and in_keep:
            seqs.append(seq)
    
    return seqs if seqs else None

def extract_mutation_info(mutated_seq, wild_type_seq):
    """Extract (position, mutant_aa) from mutated sequence vs wild type."""
    mutations = []
    for i, (wt, mut) in enumerate(zip(wild_type_seq, mutated_seq)):
        if wt != mut:
            mutations.append((i, mut))
    return mutations

def parse_mutant_string(mutant_str, wild_type_seq):
    """Parse ProteinGym mutant string (e.g., 'A45V') into (position, mutant_aa)."""
    # Format: WTletter + position + MUTletter (1-indexed in ProteinGym)
    if not mutant_str or mutant_str == 'wildtype':
        return None
    
    # Could be multi-mutant (e.g., "A45V,F100L")
    if ',' in mutant_str:
        parts = mutant_str.split(',')
    else:
        parts = [mutant_str]
    
    mutations = []
    for part in parts:
        part = part.strip()
        if len(part) < 3:
            continue
        wt_aa = part[0]
        mut_aa = part[-1]
        try:
            pos = int(part[1:-1]) - 1  # Convert to 0-indexed
            if 0 <= pos < len(wild_type_seq):
                mutations.append((pos, mut_aa))
        except ValueError:
            continue
    
    return mutations if mutations else None

def compute_spearman(predicted, actual):
    """Compute Spearman correlation, handling edge cases."""
    if len(predicted) < 2:
        return 0.0
    predicted = np.array(predicted)
    actual = np.array(actual)
    if np.std(predicted) == 0 or np.std(actual) == 0:
        return 0.0
    rho, _ = spearmanr(predicted, actual)
    if np.isnan(rho):
        return 0.0
    return rho

def compute_speed_bonus(elapsed_s):
    """Sigmoid speed bonus."""
    return SPEED_BONUS_MAX / (1 + np.exp(0.3 * (elapsed_s - SPEED_INFLECTION_S)))

def run_strategy_streaming(strategy_func, protein_id, wt_seq, mut_list, exp_scores, msa, all_sequences):
    """Run strategy on a single protein. Returns (spearman, elapsed)."""
    t0 = time.time()
    
    try:
        predicted = strategy_func(
            sequences=all_sequences,
            protein_id=protein_id,
            wild_type=wt_seq,
            mutations=mut_list,
            msa=msa
        )
        
        elapsed = time.time() - t0
        
        if predicted is None or len(predicted) != len(exp_scores):
            return 0.0, elapsed
        
        spearman = compute_spearman(predicted, exp_scores)
        return spearman, elapsed
        
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[eval] Strategy crashed on {protein_id}: {e}", file=sys.stderr)
        return 0.0, elapsed


def _process_single_protein(protein_id, reference, all_sequences, strategy_func, workspace):
    """Process a single protein: load data, run strategy, compute Spearman.
    Returns (protein_id, score, elapsed, details, mutation_sample_data).
    Designed for ThreadPoolExecutor — MSA loading is I/O bound."""
    import gc as _gc

    ref = reference.get(protein_id)
    if not ref:
        return protein_id, None, 0, None, None

    wt_seq = all_sequences.get(protein_id)
    if not wt_seq:
        return protein_id, None, 0, None, None

    muts, mut_scores, mut_codes = load_mutations(protein_id, reference)
    if muts is None:
        return protein_id, None, 0, None, None

    mut_list = list(muts)
    exp_scores = list(mut_scores)

    msa = load_msa(protein_id, ref, protein_length=len(wt_seq))
    msa_depth = len(msa) if msa else 0

    t0 = time.time()
    try:
        predicted = strategy_func(
            sequences=all_sequences,
            protein_id=protein_id,
            wild_type=wt_seq,
            mutations=mut_list,
            msa=msa
        )
        elapsed = time.time() - t0

        if predicted is None or len(predicted) != len(exp_scores):
            spearman = 0.0
            predicted = None
        else:
            spearman = compute_spearman(predicted, exp_scores)
    except Exception as e:
        elapsed = time.time() - t0
        spearman = 0.0
        predicted = None
        print(f"[eval] Strategy crashed on {protein_id}: {e}", file=sys.stderr)

    detail = {
        'spearman': float(spearman),
        'time_s': float(elapsed),
        'speed_bonus': float(compute_speed_bonus(elapsed)),
        'n_mutations': len(mut_list),
        'msa_depth': msa_depth,
        'assay_type': load_assay_type(protein_id, reference),
    }

    # Stash per-mutation data for diagnostics
    mut_sample = None
    if predicted is not None:
        entropy = compute_position_entropy(msa, len(wt_seq)) if msa else None

        mutation_classes = []
        mutation_entropy = []
        for idx in range(len(mut_codes)):
            code = mut_codes[idx] if idx < len(mut_codes) else ''
            pos_idx = None
            wt_aa = '?'
            mut_aa = '?'
            if isinstance(code, str) and len(code) >= 3 and code != 'wildtype':
                wt_aa = code[0]
                mut_aa = code[-1]
                try:
                    pos_idx = int(code[1:-1]) - 1
                except ValueError:
                    pass
            elif isinstance(code, str) and len(code) == len(wt_seq):
                for i in range(min(len(wt_seq), len(code))):
                    if wt_seq[i] != code[i]:
                        pos_idx = i
                        wt_aa = wt_seq[i]
                        mut_aa = code[i]
                        break

            if entropy and pos_idx is not None and 0 <= pos_idx < len(entropy):
                ent = entropy[pos_idx]
                mutation_entropy.append(ent)
                mutation_classes.append(classify_position(ent, wt_aa))
            else:
                mutation_entropy.append(None)
                mutation_classes.append('unknown')

        _top_idx = np.argsort(np.abs(np.array(predicted) - np.array(exp_scores)))[::-1][:50]

        mut_sample = {
            'mutant_strings': [mut_codes[i] if i < len(mut_codes) else '' for i in _top_idx],
            'predicted': np.array(predicted)[_top_idx],
            'expected': np.array(exp_scores)[_top_idx],
            'mutation_entropy': [mutation_entropy[i] for i in _top_idx],
            'mutation_burial': [mutation_classes[i] for i in _top_idx],
            'wt_seq': wt_seq,
        }

    del msa
    _gc.collect()

    print(f"[eval] {protein_id}: Spearman={spearman:.4f}, time={elapsed:.1f}s, msa_depth={msa_depth}", file=sys.stderr)

    return protein_id, spearman, elapsed, detail, mut_sample


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', required=True, help='Workspace directory')
    parser.add_argument('--smoke', action='store_true', help='Run smoke test (5 proteins)')
    parser.add_argument('--workers', type=int, default=1,
                        help='Parallel workers (default: 1=serial). On 2-core machines use 2 '
                             'for I/O overlap — GIL keeps 1 core free for other work.')
    args = parser.parse_args()
    
    workspace = args.dir
    
    # Determine protein set
    proteins_to_eval = EVAL_PROTEINS[:5] if args.smoke else EVAL_PROTEINS
    
    # Load reference data
    reference = load_reference()
    
    # Load only wild-type sequences (lightweight — just strings)
    all_sequences = {}
    for protein_id in proteins_to_eval:
        ref = reference.get(protein_id)
        if ref:
            wt_seq = ref.get('target_seq', '')
            if wt_seq:
                all_sequences[protein_id] = wt_seq
    
    if not all_sequences:
        print(json.dumps({"score": 0.0, "error": "no protein data loaded"}))
        sys.exit(1)
    
    # Load strategy
    strategy_path = os.path.join(workspace, 'staging_strategy.py')
    if not os.path.exists(strategy_path):
        strategy_path = os.path.join(EVAL_DIR, 'active', 'strategy.py')
    
    if not os.path.exists(strategy_path):
        print(json.dumps({"score": 0.0, "error": "no strategy found"}))
        sys.exit(1)
    
    # Import strategy module
    spec = importlib.util.spec_from_file_location("strategy", strategy_path)
    strategy_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strategy_mod)
    
    if not hasattr(strategy_mod, 'score_mutations'):
        print(json.dumps({"score": 0.0, "error": "strategy missing score_mutations"}))
        sys.exit(1)
    
    strategy_func = strategy_mod.score_mutations
    
    # Process proteins — parallel if --workers > 1, serial otherwise
    scores = {}
    times = {}
    details = {}
    mutation_samples = {}  # protein_id -> per-mutation data (for diagnostics)

    if args.workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print(f"[eval] Running with {args.workers} workers (thread-based)", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_process_single_protein, pid, reference, all_sequences, strategy_func, workspace): pid
                for pid in proteins_to_eval
            }
            for future in as_completed(futures):
                pid = futures[future]
                try:
                    protein_id, spearman, elapsed, detail, mut_sample = future.result()
                    if spearman is not None:
                        scores[protein_id] = spearman
                        times[protein_id] = elapsed
                        details[protein_id] = detail
                        if mut_sample is not None:
                            mutation_samples[protein_id] = mut_sample
                except Exception as e:
                    print(f"[eval] Worker error on {pid}: {e}", file=sys.stderr)
                    scores[pid] = 0.0
                    times[pid] = 0.0
                    details[pid] = {'spearman': 0.0, 'time_s': 0.0, 'speed_bonus': 0.0,
                                    'n_mutations': 0, 'msa_depth': 0, 'assay_type': 'Unknown'}
    else:
        # Serial mode (original behavior)
        for protein_id in proteins_to_eval:
            pid, spearman, elapsed, detail, mut_sample = _process_single_protein(
                protein_id, reference, all_sequences, strategy_func, workspace)
            if spearman is not None:
                scores[pid] = spearman
                times[pid] = elapsed
                details[pid] = detail
                if mut_sample is not None:
                    mutation_samples[pid] = mut_sample
    
    # Compute aggregate score
    spearmans = list(scores.values())
    avg_spearman = float(np.mean(spearmans)) if spearmans else 0.0
    
    avg_time = float(np.mean(list(times.values()))) if times else 0.0
    speed_bonus = float(compute_speed_bonus(avg_time))
    
    total_score = avg_spearman + speed_bonus
    
    # Build mutation-level diagnostics for bottom 10 proteins
    sorted_proteins = sorted(scores.items(), key=lambda x: x[1])
    bottom_10 = [pid for pid, _ in sorted_proteins[:10]]
    
    mutation_diagnostics = {}
    sub_class_stats = {}  # sub_class -> {count, total_error, total_abs_error}
    
    for pid in bottom_10:
        if pid not in mutation_samples:
            continue
        ms = mutation_samples[pid]
        muts = ms['mutant_strings']
        preds = ms['predicted']
        exps = ms['expected']
        wt = ms['wt_seq']
        
        # Aggregate substitution class stats across ALL mutations in this protein
        for idx in range(len(preds)):
            mut_str = muts[idx] if idx < len(muts) else ''
            wt_aa, mut_aa = '?', '?'
            if isinstance(mut_str, str) and len(mut_str) >= 3 and mut_str != 'wildtype':
                wt_aa = mut_str[0]
                mut_aa = mut_str[-1]
            elif isinstance(mut_str, str) and len(mut_str) == len(wt):
                diffs = [(i, wt[i], mut_str[i]) for i in range(min(len(wt), len(mut_str))) if wt[i] != mut_str[i]]
                if diffs:
                    wt_aa = diffs[0][1]
                    mut_aa = diffs[0][2]
            if wt_aa != '?' and mut_aa != '?':
                sc = _substitution_class(wt_aa, mut_aa)
                if sc not in sub_class_stats:
                    sub_class_stats[sc] = {'count': 0, 'total_error': 0.0, 'total_abs_error': 0.0}
                err = float(preds[idx] - exps[idx])
                sub_class_stats[sc]['count'] += 1
                sub_class_stats[sc]['total_error'] += err
                sub_class_stats[sc]['total_abs_error'] += abs(err)
        
        # Compute per-mutation absolute errors for worst list
        errors = [(abs(float(p - e)), i) for i, (p, e) in enumerate(zip(preds, exps))]
        errors.sort(reverse=True)
        
        # Sample: top 20 worst predictions
        sampled = []
        for abs_err, idx in errors[:20]:
            # Extract position info from mutation string or sequence comparison
            mut_str = muts[idx] if idx < len(muts) else '?'
            if isinstance(mut_str, str) and len(mut_str) >= 3 and mut_str != 'wildtype':
                # ProteinGym format: A45V
                wt_aa = mut_str[0]
                mut_aa = mut_str[-1]
                try:
                    pos = int(mut_str[1:-1])
                except ValueError:
                    pos = 0
            elif isinstance(mut_str, str) and len(mut_str) == len(wt):
                # Full sequence — find the change
                diffs = [(i+1, wt[i], mut_str[i]) for i in range(min(len(wt), len(mut_str))) if wt[i] != mut_str[i]]
                if diffs:
                    pos, wt_aa, mut_aa = diffs[0]
                else:
                    pos, wt_aa, mut_aa = 0, '?', '?'
            else:
                pos, wt_aa, mut_aa = 0, '?', '?'
            
            sampled.append({
                'mutant': mut_str[:30] if isinstance(mut_str, str) else '?',
                'pos': pos,
                'wt_aa': wt_aa,
                'mut_aa': mut_aa,
                'sub_class': _substitution_class(wt_aa, mut_aa),
                'predicted': round(float(preds[idx]), 4),
                'expected': round(float(exps[idx]), 4),
                'error': round(float(preds[idx] - exps[idx]), 4),
            })
        
        mutation_diagnostics[pid] = {
            'spearman': scores[pid],
            'n_mutations': len(preds),
            'worst_mutations': sampled,
        }
    
    # Substitution class summary
    sub_summary = {}
    for sc, stats in sorted(sub_class_stats.items(), key=lambda x: x[1]['total_abs_error']/x[1]['count'] if x[1]['count'] > 0 else 0, reverse=True):
        n = stats['count']
        sub_summary[sc] = {
            'count': n,
            'mean_error': round(stats['total_error'] / n, 3) if n else 0,
            'mean_abs_error': round(stats['total_abs_error'] / n, 3) if n else 0,
        }
    
    # ── Assay type breakdown ──────────────────────────────────────────
    assay_groups = {}
    for pid, sp in scores.items():
        at = details[pid].get('assay_type', 'Unknown')
        assay_groups.setdefault(at, []).append(sp)
    assay_breakdown = {}
    for at, sp_list in assay_groups.items():
        assay_breakdown[at] = {
            'count': len(sp_list),
            'avg_spearman': round(sum(sp_list) / len(sp_list), 4) if sp_list else 0,
        }
    
    # ── Conservation-error correlation (bottom 10 proteins) ──────────
    # For each mutation in bottom-10: pair entropy with abs error
    entropy_error_pairs = []  # [(entropy, abs_error), ...]
    for pid in bottom_10:
        if pid not in mutation_samples:
            continue
        ms = mutation_samples[pid]
        entropies = ms.get('mutation_entropy', [])
        preds = ms['predicted']
        exps = ms['expected']
        for idx in range(min(len(entropies), len(preds))):
            if entropies[idx] is not None:
                abs_err = abs(float(preds[idx] - exps[idx]))
                entropy_error_pairs.append((entropies[idx], abs_err))
    
    conservation_analysis = {}
    if entropy_error_pairs:
        # Bin by entropy level
        bins = {'conserved (<1.0)': [], 'moderate (1.0-2.0)': [], 'variable (2.0-3.0)': [], 'hypervariable (≥3.0)': []}
        for ent, err in entropy_error_pairs:
            if ent < 1.0: bins['conserved (<1.0)'].append(err)
            elif ent < 2.0: bins['moderate (1.0-2.0)'].append(err)
            elif ent < 3.0: bins['variable (2.0-3.0)'].append(err)
            else: bins['hypervariable (≥3.0)'].append(err)
        for label, errors in bins.items():
            if errors:
                conservation_analysis[label] = {
                    'count': len(errors),
                    'mean_abs_error': round(sum(errors) / len(errors), 3),
                }
    
    # ── Burial proxy breakdown ───────────────────────────────────────
    burial_groups = {}
    for pid in bottom_10:
        if pid not in mutation_samples:
            continue
        ms = mutation_samples[pid]
        burials = ms.get('mutation_burial', [])
        preds = ms['predicted']
        exps = ms['expected']
        for idx in range(min(len(burials), len(preds))):
            b = burials[idx]
            if b not in burial_groups:
                burial_groups[b] = {'count': 0, 'total_abs_error': 0.0}
            burial_groups[b]['count'] += 1
            burial_groups[b]['total_abs_error'] += abs(float(preds[idx] - exps[idx]))
    burial_analysis = {}
    for b, stats in burial_groups.items():
        n = stats['count']
        burial_analysis[b] = {
            'count': n,
            'mean_abs_error': round(stats['total_abs_error'] / n, 3) if n else 0,
        }
    
    # Output
    result = {
        "score": total_score,
        "avg_spearman": avg_spearman,
        "avg_time_s": avg_time,
        "speed_bonus": speed_bonus,
        "n_proteins": len(scores),
        "details": details,
        "mutation_diagnostics": mutation_diagnostics,
        "substitution_analysis": sub_summary,
        "assay_breakdown": assay_breakdown,
        "conservation_analysis": conservation_analysis,
        "burial_analysis": burial_analysis,
    }
    
    print(json.dumps(result))

if __name__ == '__main__':
    main()
