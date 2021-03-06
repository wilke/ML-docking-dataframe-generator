from time import time
import numpy as np
import pandas as pd
from joblib import Parallel, delayed


def canon_single_smile(smi):
    """ Canonicalize single SMILES string. """
    from rdkit import Chem
    try:
        mol = Chem.MolFromSmiles( smi )
        can_smi = Chem.MolToSmiles(mol, canonical=True)
    except:
        print(f'Error in smile: {smi}')
        can_smi = np.nan
    return can_smi


def canon_df(df, smi_name='smiles', par_jobs=16):
    """ Canonicalize the smiles sting in column name smi_name. """
    smi_vec = []
    t0 = time()
    if par_jobs>1:
        smi_vec = Parallel(n_jobs=par_jobs, verbose=1)(
                delayed(canon_single_smile)(smi) for smi in df[smi_name].tolist())
    else:
        for i, smi in enumerate(df[smi_name].values):
            if i%100000==0:
                print('{}: {:.2f} mins'.format(i, (time()-t0)/60 ))
            can_smi = canon_single_smile( smi )
            smi_vec.append( can_smi ) # TODO: consider return this, instead of modifying df
    df.loc[:, 'smiles'] = smi_vec
    return df


def canon_smiles(smiles, par_jobs=16):
    """ Canonicalize each smile in the smiles array. """
    smi_vec = []
    t0 = time()
    if par_jobs>1:
        smi_vec = Parallel(n_jobs=par_jobs, verbose=1)(
                delayed(canon_single_smile)(smi) for smi in smiles)
    else:
        for i, smi in enumerate(smiles):
            if i%100000==0:
                print('{}: {:.2f} mins'.format(i, (time()-t0)/60 ))
            can_smi = canon_single_smile( smi )
            smi_vec.append( can_smi )
    return smi_vec


def fps_single_smile(smi, radius=2, nbits=2048):
    """ Convert single SMILES into Morgan fingerprints.
    From www.rdkit.org/docs/GettingStartedInPython.html#morgan-fingerprints-circular-fingerprints:
    When comparing the ECFP/FCFP FPs and the Morgan FPs generated by the RDKit, remember that the
    4 in ECFP4 corresponds to the diameter of the atom environments considered, while the Morgan FPs
    take a radius parameter. So when radius=2, this is roughly equivalent to ECFP4 and FCFP4."""
    # Xuefeng:
    # canonical_smile=pybel.readstring("smi", row["smiles"]).write("can").strip()
    # m1 = Chem.MolFromSmiles(canonical_smile)
    # ecfp4 = AllChem.GetMorganFingerprintAsBitVect(m1, 2, nBits=1024)
    # ecfp4_fingers = np.array(ecfp4).tolist()
    # Stackoverflow:
    # stackoverflow.com/questions/54809506/
    from rdkit import Chem
    from rdkit.Chem import AllChem, DataStructs
    mol = Chem.MolFromSmiles( smi )
    fp = AllChem.GetMorganFingerprintAsBitVect(mol=mol, radius=radius, nBits=nbits)
    fp_arr = np.array(fp) # .tolist()
    res = {'smiles': smi, 'fps': fp_arr}
    return res


def smiles_to_fps(df, radius=2, nbits=2048, smi_name='smiles', par_jobs=16):
    """ Canonicalize a smiles vector and generate df of FPs. """
    res = Parallel(n_jobs=par_jobs, verbose=1)(
            delayed(fps_single_smile)(smi, radius=radius) for smi in df[smi_name].tolist())
    fps_list = [dct['fps'] for dct in res]
    smi_list = [dct['smiles'] for dct in res]
    fps_df = pd.DataFrame( np.vstack( fps_list ) )
    fps_df.insert(loc=0, column='smiles', value=smi_list)
    return fps_df


def smile_to_mol(smi):
    """ ... """
    try:
        mol = Chem.MolFromSmiles(smi)
    except:
        print(f'Error: smiles={smi}')
        mol = np.nan
    return mol


def smiles_to_mordred(df, smi_name='smiles', par_jobs=16):
    """ Canonicalize a smiles vector and generate df of Mordred descriptors. """
    from rdkit import Chem
    from mordred import Calculator, descriptors

    # Create descriptor calculator with all descriptors
    calc = Calculator(descriptors, ignore_3D=True)
    # print( len(calc.descriptors) )
    # print( len(Calculator(descriptors, ignore_3D=True, version="1.0.0")) )

    # Calc molecules
    mols = [Chem.MolFromSmiles(smi) for smi in df[smi_name].values]

    # Molecules to descriptors
    # mordred-descriptor.github.io/documentation/master/_modules/mordred/_base/calculator.html#Calculator.pandas
    dsc = calc.pandas( mols, nproc=par_jobs, nmols=None, quiet=False, ipynb=False )
    dsc = pd.concat([df, dsc], axis=1)
    return dsc


