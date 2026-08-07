#!/usr/bin/env python3
"""ProteinGym smoke test (Tier 1). Quick check on 5 proteins.
Agent triggers this via staging_smoke_trigger.json before submitting.

Runs the agent's staging_strategy.py on 5 DMS proteins and returns
real Spearman + speed bonus per protein. Smoke results are reused by eval.
"""
import sys, os, json, time, importlib.util, threading, csv, hashlib
import numpy as np
from scipy.stats import spearmanr

# ── Configuration ──────────────────────────────────────────────────────────
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('PROTEINGYM_DATA',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'DMS_ProteinGym_substitutions'))
REF_FILE = os.environ.get('PROTEINGYM_REFERENCE',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'DMS_substitutions.csv'))
MSA_DIR = os.environ.get('PROTEINGYM_MSA',
    os.path.join(os.path.dirname(EVAL_DIR), 'data', 'DMS_msa_files'))

# 5 smoke proteins — stratified sample mirroring benchmark distribution
# 2 Human, 1 Prokaryote, 1 Eukaryote (via Virus proxy), 1 Virus
# Covers: Stability, Activity, Binding, OrganismalFitness assay types
# Avoids outlier proteins that score <0.1 with any strategy
SMOKE_PROTEINS = [
    'A4_HUMAN_Seuma_2022',                    # Human, Stability, N_eff=62
    'PTEN_HUMAN_Mighell_2018',                 # Human, Activity, N_eff=1501
    'SPIKE_SARS2_Starr_2020_binding',          # Virus, Binding, N_eff=1347
    'A0A192B1T2_9HIV1_Haddox_2018',            # Virus, OrganismalFitness, N_eff=36470
    'A0A247D711_LISMN_Stadelmann_2021',        # Prokaryote, Activity, N_eff=9
]


STRATEGY_TIMEOUT = 300  # seconds per protein (matches eval)
SPEED_BONUS_MAX = 0.002
SPEED_INFLECTION_S = 30

# ── Helpers ────────────────────────────────────────────────────────────────

def load_reference():
    with open(REF_FILE) as f:
        reader = csv.DictReader(f)
        return {row['DMS_id']: row for row in reader}

def load_mutations(protein_id, reference):
    dms_file = os.path.join(DATA_DIR, f'{protein_id}.csv')
    if not os.path.exists(dms_file):
        return None, None
    mutations = []
    scores = []
    with open(dms_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if 'mutant' in row:
                mutations.append(row['mutant'])
            elif 'mutated_sequence' in row:
                mutations.append(row['mutated_sequence'])
            scores.append(float(row['DMS_score']))
    return mutations, scores

MSA_SUBSAMPLE_SEED = 42
MSA_MIN_DEPTH = 500
MSA_DEPTH_FACTOR = 10

def compute_msa_sample_n(total_seqs, protein_length):
    return max(MSA_MIN_DEPTH, min(total_seqs, MSA_DEPTH_FACTOR * protein_length))

def load_msa(protein_id, reference, protein_length=None):
    msa_filename = reference.get(protein_id, {}).get('MSA_filename', '').strip()
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
        sample_n = 10_000
    
    if total_seqs <= sample_n:
        seqs = []
        seq = ''
        with open(msa_path) as f:
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
    
    # Reservoir sample
    import random
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

def compute_spearman(predicted, actual):
    if len(predicted) < 2:
        return 0.0
    predicted = np.array(predicted)
    actual = np.array(actual)
    if np.std(predicted) == 0 or np.std(actual) == 0:
        return 0.0
    rho, _ = spearmanr(predicted, actual)
    if np.isnan(rho):
        return 0.0
    return float(rho)

def speed_bonus(elapsed_s):
    return SPEED_BONUS_MAX / (1.0 + np.exp(0.3 * (elapsed_s - SPEED_INFLECTION_S)))

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', default=os.path.join(os.path.dirname(EVAL_DIR), 'workspace'),
                        help='Workspace directory containing staging_strategy.py')
    args = parser.parse_args()

    WORKSPACE = args.workspace
    STRATEGY_PATH = os.path.join(WORKSPACE, 'staging_strategy.py')
    RESULT_PATH = os.path.join(WORKSPACE, 'staging_smoke_result.json')

    if not os.path.exists(STRATEGY_PATH):
        print(json.dumps({'error': 'staging_strategy.py not found'}))
        sys.exit(1)

    reference = load_reference()
    results = {}

    # Load strategy module once
    spec = importlib.util.spec_from_file_location('_strategy', STRATEGY_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        # Strategy itself won't import — all proteins crash
        for pid in SMOKE_PROTEINS:
            results[pid] = {'status': 'crash', 'error': str(e)[:200]}
        output = {
            'profiles': results,
            'avg_spearman': 0.0,
            'avg_elapsed_s': 0.0,
            'n_ok': 0,
            'n_total': len(SMOKE_PROTEINS),
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        with open(RESULT_PATH, 'w') as f:
            json.dump(output, f, indent=2)
        print(json.dumps(output))
        return

    # Load all sequences and mutations upfront
    sequences = {}
    all_mutations = {}
    all_msas = {}

    for pid in SMOKE_PROTEINS:
        ref = reference.get(pid)
        if not ref:
            results[pid] = {'status': 'skip', 'reason': 'not in reference'}
            continue
        wt_seq = ref.get('target_seq', '')
        if not wt_seq:
            results[pid] = {'status': 'skip', 'reason': 'no target sequence'}
            continue
        sequences[pid] = wt_seq

        muts, scores = load_mutations(pid, reference)
        if muts is None:
            results[pid] = {'status': 'skip', 'reason': 'no mutation data'}
            continue
        all_mutations[pid] = (muts, scores)

        msa = load_msa(pid, reference, protein_length=len(wt_seq))
        if msa:
            all_msas[pid] = msa

    # Run strategy on each protein
    for pid in SMOKE_PROTEINS:
        if pid not in all_mutations:
            continue  # already marked skip/crash

        muts, exp_scores = all_mutations[pid]

        holder = [None]
        exc_holder = [None]
        t0 = time.time()

        def _target(pid=pid, muts=muts):
            try:
                holder[0] = mod.score_mutations(
                    sequences=sequences,
                    protein_id=pid,
                    wild_type=sequences[pid],
                    mutations=muts,
                    msa=all_msas.get(pid),
                )
            except Exception as e:
                exc_holder[0] = e

        th = threading.Thread(target=_target, daemon=True)
        th.start()
        th.join(STRATEGY_TIMEOUT)
        elapsed = time.time() - t0

        if th.is_alive():
            results[pid] = {'status': 'timeout', 'elapsed_s': round(elapsed, 1)}
            continue
        if exc_holder[0] is not None:
            results[pid] = {'status': 'crash', 'error': str(exc_holder[0])[:200], 'elapsed_s': round(elapsed, 1)}
            continue

        predicted = holder[0]
        if predicted is None or len(predicted) != len(exp_scores):
            results[pid] = {
                'status': 'crash',
                'error': f'expected {len(exp_scores)} scores, got {len(predicted) if predicted else 0}',
                'elapsed_s': round(elapsed, 1),
            }
            continue

        sp = compute_spearman(predicted, exp_scores)
        sb = float(speed_bonus(elapsed))

        results[pid] = {
            'status': 'ok',
            'spearman': round(sp, 4),
            'speed_bonus': round(sb, 6),
            'primary': round(sp + sb, 4),
            'elapsed_s': round(elapsed, 1),
            'n_mutations': len(exp_scores),
        }

    # Aggregate
    scored = [r for r in results.values() if 'primary' in r]
    avg_primary = sum(r['primary'] for r in scored) / len(scored) if scored else 0.0
    avg_spearman = sum(r.get('spearman', 0.0) for r in scored) / len(scored) if scored else 0.0
    avg_elapsed = sum(r.get('elapsed_s', 0.0) for r in scored) / len(scored) if scored else 0.0

    # Hash the strategy file so the agent can verify results match current code
    strategy_hash = hashlib.md5(open(STRATEGY_PATH, 'rb').read()).hexdigest()[:8]

    output = {
        'profiles': results,
        'avg_primary': round(avg_primary, 4),
        'avg_spearman': round(avg_spearman, 4),
        'avg_elapsed_s': round(avg_elapsed, 1),
        'n_ok': len(scored),
        'n_total': len(SMOKE_PROTEINS),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'strategy_hash': strategy_hash,
    }

    with open(RESULT_PATH, 'w') as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output))


if __name__ == '__main__':
    main()
