"""
This script parses docking score results and merges the
scores of each target with mulitple types of molecular features.
An ML dataframe, containing a single feature type is saved into a file.
"""
import warnings
warnings.filterwarnings('ignore')

import os
import sys
from pathlib import Path
from time import time
import argparse
from pprint import pformat

from joblib import Parallel, delayed

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

filepath = Path(__file__).resolve().parent

# Utils
from utils.classlogger import Logger
from utils.utils import load_data, get_print_func, drop_dup_rows
from ml.data import extract_subset_fea, extract_subset_fea_col_names
from utils.smiles import canon_smiles

# Features
# FEA_PATH = filepath/'../data/raw/features/BL1/ena+db.smi.desc.parquet' # BL1 (ENA+DB: ~305K)
# FEA_PATH = filepath/'../data/raw/features/BL2/BL2.dsc.parquet' # BL2 (ENA+DB: ~305K)
FEA_PATH = filepath/'../data/raw/features/BL2/BL2.dsc.parquet' # BL2 (ENA+DB: ~305K)
meta_cols = ['TITLE', 'SMILES']

# Docking
SCORES_MAIN_PATH = filepath/'../data/raw/raw_data'
# SCORES_PATH = SCORES_MAIN_PATH/'V3_docking_data_april_16/docking_data_out_v3.2.csv'
# SCORES_PATH = SCORES_MAIN_PATH/'V3_docking_data_april_16/docking_data_out_v3.2.csv'
# SCORES_PATH = SCORES_MAIN_PATH/'V5_docking_data_april_24/pivot_SMILES.csv'
SCORES_PATH = SCORES_MAIN_PATH/'V5_docking_data_april_24/pivot_TITLE.csv'


def parse_args(args):
    parser = argparse.ArgumentParser(description='Generate ML dataframes from molecular features and docking scores.')
    parser.add_argument('-sp', '--scores_path', default=str(SCORES_PATH), type=str,
                        help='Path to docking score resutls file (default: {SCORES_PATH}).')
    parser.add_argument('--fea_path', default=str(FEA_PATH), type=str,
                        help='Path to molecular features file (default: {FEA_PATH}).')
    parser.add_argument('-od', '--outdir', default=None, type=str,
                        help=f'Output dir (default: None).')
    parser.add_argument('-f', '--fea_list', default=['dsc'], nargs='+', type=str,
                        help=f'Prefix of feature column names (default: dsc).')
    parser.add_argument('--q_bins', default=0.025, type=float,
                        help=f'Quantile to bin the docking score (default: 0.025).')
    parser.add_argument('--par_jobs', default=1, type=int, 
                        help=f'Number of joblib parallel jobs (default: 1).')
    # args, other_args = parser.parse_known_args( args )
    args= parser.parse_args( args )
    return args


def gen_ml_df(dd, trg_name, meta_cols=['TITLE', 'SMILES'], fea_list=['dsc'],
              score_name='reg', q_cls=0.025, bin_th=2.0, print_fn=print,
              outdir=Path('out'), outfigs=Path('outfigs')):
    """ Generate a single ML dataframe for the specified target column trg_name.
    Args:
        dd : dataframe with (molecules x targets) where the first col is TITLE
        trg_name : a column in dd representing the target 
        meta_cols : metadata columns to include in the dataframe
        score_name : rename the trg_name with score_name
        q_cls : quantile value to compute along the docking scores to generate the 'cls' col
        bin_th : threshold value of docking score to generate the 'binner' col
    
    Returns:
        dd_trg : the ML dataframe 
    """
    print_fn( f'Processing {trg_name} ...' )
    res = {}
    res['target'] = trg_name

    meta_cols = set(meta_cols).intersection(set(dd.columns.tolist()))
    meta_cols = [i for i in meta_cols]

    # fea_list = ['dsc', 'ecfp2', 'ecfp4', 'ecfp6']
    # fea_list = ['dsc']
    fea_sep = '.'
    fea_cols = extract_subset_fea_col_names(dd, fea_list=fea_list, fea_sep=fea_sep)
    cols = [trg_name] + meta_cols + fea_cols
    dd_trg = dd[ cols ]
    del dd

    # Drop NaN scores
    dd_trg = dd_trg[ ~dd_trg[trg_name].isna() ].reset_index(drop=True)

    # Rename the scores col
    dd_trg = dd_trg.rename( columns={trg_name: score_name} )

    # File name
    fname = 'ml.' + trg_name
    
    # Transform scores to positive
    dd_trg[score_name] = abs( np.clip(dd_trg[score_name], a_min=None, a_max=0) )
    res['min'], res['max'] = dd_trg[score_name].min(), dd_trg[score_name].max()
    bins = 50
    """
    p = dd[score_name].hist(bins=bins);
    p.set_title(f'Scores Clipped to 0: {fname}');
    p.set_ylabel('Count'); p.set_xlabel('Docking Score');
    plt.savefig(outfigs/f'dock_scores_clipped_{fname}.png');
    """
    
    # Add binner
    binner = [1 if x>=bin_th else 0 for x in dd_trg[score_name]]
    dd_trg.insert(loc=1, column='binner', value=binner)

    # -----------------------------------------    
    # Create binner
    # -----------------------------------------      
    # Find quantile value
    if dd_trg[score_name].min() >= 0: # if scores were transformed to >=0
        q_cls = 1.0 - q_cls
    cls_th = dd_trg[score_name].quantile(q=q_cls)
    res['cls_th'] = cls_th
    print_fn('Quantile score (q_cls={:.3f}): {:.3f}'.format( q_cls, cls_th ))

    # Generate a classification target col
    if dd_trg[score_name].min() >= 0: # if scores were transformed to >=0
        value = (dd_trg[score_name] >= cls_th).astype(int)
    else:
        value = (dd_trg[score_name] <= cls_th).astype(int)
    dd_trg.insert(loc=1, column='cls', value=value)
    # print_fn('Ratio {:.3f}'.format( dd['dock_bin'].sum() / dd.shape[0] ))

    # Plot
    hist, bin_edges = np.histogram(dd_trg[score_name], bins=bins)
    x = np.ones((10,)) * cls_th
    y = np.linspace(0, hist.max(), len(x))

    fig, ax = plt.subplots()
    plt.hist(dd_trg[score_name], bins=bins, density=False, facecolor='b', alpha=0.5)
    plt.title(f'Scores Clipped to 0: {fname}');
    plt.ylabel('Count'); plt.xlabel('Docking Score');
    plt.plot(x, y, 'r--', alpha=0.7, label=f'{q_cls}-th quantile')
    plt.grid(True)
    plt.savefig(outfigs/f'dock.score.bin.{fname}.png')

    # Separate the features
    def extract_and_save_fea( df, fea, to_csv=False ):
        """ Extract specific feature type (including metadata) and
        save to file. 
        """
        name = fea
        fea_prfx_drop = [i for i in fea_list if i!=fea]
        fea_cols_drop = extract_subset_fea_col_names(df, fea_list=fea_prfx_drop, fea_sep=fea_sep)
        data = df.drop( columns=fea_cols_drop )
        outpath_name = outdir/(fname+f'.{name}')
        data.to_parquet( str(outpath_name)+'.parquet' )
        if to_csv:
            data.to_csv( str(outpath_name)+'.csv', index=False )
        return data

    print_fn( f'Create and save dataframes ...' )
    for fea in fea_list:
        to_csv = False if 'dsc' in fea else True
        dsc_df = extract_and_save_fea( dd_trg, fea=fea, to_csv=to_csv )

    # Scale desciptors and save scaler (save raw features rather the scaled)
    if sum([True for i in fea_list if 'dsc' in i]):
        dsc_prfx = ('dsc'+fea_sep)
        from sklearn.preprocessing import StandardScaler
        import joblib
        xdata = extract_subset_fea(dsc_df, fea_list='dsc', fea_sep=fea_sep)
        cols = xdata.columns
        sc = StandardScaler( with_mean=True, with_std=True )
        sc.fit( xdata )
        sc_outpath = outdir/(fname+f'.dsc.scaler.pkl')
        joblib.dump(sc, sc_outpath)
        # sc_ = joblib.load( sc_outpath ) 

        # We decided to remove the feature-specific prefixes for descriptors
        dsc_df = dsc_df.rename(columns={c: c.split(dsc_prfx)[-1] if dsc_prfx in c else c for c in dsc_df.columns})
        dsc_df.to_csv( outdir/(fname+'.dsc.csv'), index=False)        

    try:
        import lightgbm as lgb
        from sklearn.model_selection import train_test_split
        from datasplit.splitter import data_splitter
        from ml.evals import calc_preds, calc_scores, dump_preds
        ml_model_def = lgb.LGBMRegressor
        ml_init_args = {'n_jobs': 8}
        ml_fit_args = {'verbose': False, 'early_stopping_rounds': 10}
        model = ml_model_def( **ml_init_args )
        ydata = dd_trg['reg']
        xdata = extract_subset_fea(dd_trg, fea_list=fea_list, fea_sep=fea_sep)
        x_, xte, y_, yte = train_test_split(xdata, ydata, test_size=0.2)
        xtr, xvl, ytr, yvl = train_test_split(x_, y_, test_size=0.2)
        ml_fit_args['eval_set'] = (xvl, yvl)
        model.fit(xtr, ytr, **ml_fit_args)
        y_pred, y_true = calc_preds(model, x=xte, y=yte, mltype='reg')
        te_scores = calc_scores(y_true=y_true, y_pred=y_pred, mltype='reg', metrics=None)
        res['r2'] = te_scores['r2']
        res['mae'] = te_scores['median_absolute_error']
    except:
        print('Could not import lightgbm.')

    return res


def run(args):
    t0=time()
    scores_path = Path( args['scores_path'] ).resolve()
    fea_path = Path( args['fea_path'] ).resolve()
    par_jobs = int( args['par_jobs'] )
    fea_list = args['fea_list']
    assert par_jobs > 0, f"The arg 'par_jobs' must be at least 1 (got {par_jobs})"

    if args['outdir'] is not None:
        outdir = Path( args['outdir'] ).resolve()
    else:
        batch_name = scores_path.parent.name
        outdir = Path( filepath/'../out'/batch_name ).resolve()

    outfigs = outdir/'figs'
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(outfigs, exist_ok=True)
    args['outdir'] = outdir
    
    # Logger
    lg = Logger( outdir/'gen.ml.data.log' )
    print_fn = get_print_func( lg.logger )
    print_fn(f'File path: {filepath}')
    print_fn(f'\n{pformat(args)}')
    
    print_fn('\nDocking scores path {}'.format( scores_path ))
    print_fn('Features path       {}'.format( fea_path ))
    print_fn('Outdir path         {}'.format( outdir ))

    # -----------------------------------------
    # Load data (features and docking scores)
    # -----------------------------------------    
    # Features (with SMILES)
    print_fn('\nLoad features ...')
    fea = load_data( fea_path )
    print_fn('Features {}'.format( fea.shape ))
    fea = drop_dup_rows(fea, print_fn=print_fn)

    # Docking scores
    print_fn('\nLoad docking scores ...')
    rsp = load_data( args['scores_path'] )
    print_fn('Docking {}'.format( rsp.shape ))
    rsp = drop_dup_rows(rsp, print_fn=print_fn)

    # # Check that 'SMILES' col exists
    # if 'SMILES' in rsp.columns:
    #     rsp = rsp.rename(columns={'SMILES': 'SMILES'})
    # assert 'SMILES' in rsp.columns, "Column 'SMILES' must exists in the docking scores file."

    # print_fn('\nCanonicalize SMILES ...')
    # can_smi_vec = canon_SMILES( rsp['SMILES'], par_jobs=args['par_jobs'] )
    # can_smi_vec = pd.Series(can_smi_vec)

    # # Save to file bad SMILES (that were not canonicalized)
    # nan_ids = can_smi_vec.isna()
    # bad_smi = rsp[ nan_ids ]
    # if len(bad_smi)>0:
    #     bad_smi.to_csv(outdir/'smi_canon_err.csv', index=False)

    # # Keep the good (canonicalized) SMILES
    # rsp['SMILES'] = can_smi_vec
    # rsp = rsp[ ~nan_ids ].reset_index(drop=True)

    print_fn( '\n{}'.format( rsp.columns.tolist() ))
    print_fn( '\n{}\n'.format( rsp.iloc[:3,:4] ))

    # -----------------------------------------    
    # Merge features with dock scores
    # -----------------------------------------    
    # merger = 'SMILES'
    merger = 'TITLE'
    assert merger in rsp.columns, f"Column '{merger}' must exist in the docking scores file."
    unq_smiles = set( rsp[merger] ).intersection( set(fea[merger]) )
    print_fn( 'Unique {} in rsp: {}'.format( merger, rsp[merger].nunique() ))
    print_fn( 'Unique {} in fea: {}'.format( merger, fea[merger].nunique() ))
    print_fn( 'Intersect on {}:  {}'.format( merger, len(unq_smiles) ))

    print_fn(f'\nMerge features with docking scores on {merger} ...')
    dd = pd.merge(rsp, fea, on=merger, how='inner')
    print_fn('Merged {}'.format( dd.shape ))
    print_fn('Unique {} in final df: {}'.format( merger, dd[merger].nunique() ))
    trg_names = rsp.columns[1:].tolist()
    del rsp, fea

    score_name = 'reg' # unified name for docking scores column in all output dfs
    bin_th = 2.0 # threshold value for the binner column (classifier)
    kwargs = { 'dd': dd, 'meta_cols': meta_cols, 'fea_list': fea_list,
               'score_name': score_name, 'q_cls': args['q_bins'], 'bin_th': bin_th,
               'print_fn': print_fn, 'outdir': outdir, 'outfigs': outfigs }

    if par_jobs > 1:
        # https://joblib.readthedocs.io/en/latest/parallel.html
        results = Parallel(n_jobs=par_jobs, verbose=20)(
                delayed(gen_ml_df)(trg_name=trg, **kwargs) for trg in trg_names )
    else:
        results = [] # docking summary including ML baseline scores
        for trg in trg_names:
            res = gen_ml_df(trg_name=trg, **kwargs)
            results.append( res )

    results = np.round(pd.DataFrame(results), decimals=3)
    results.to_csv( outdir/'dock.ml.baseline.csv', index=False )

    # --------------------------------------------------------
    print_fn('\nRuntime {:.2f} mins'.format( (time()-t0)/60 ))
    print_fn('Done.')
    lg.kill_logger()
    
    
def main(args):
    args = parse_args(args)
    args = vars(args)
    run(args)


if __name__ == '__main__':
    main(sys.argv[1:])


