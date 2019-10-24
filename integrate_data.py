import pandas as pd
import numpy as np
import re
import sys
from sqlalchemy import create_engine
from decouple import AutoConfig
from utils import clean_author_name

def extract_projeto(s, law_type=None):
    clean_s = s.replace('.', '').replace("//", "/")
    clean_s = re.sub('\s', '', clean_s)
    if law_type == 'lei':
        m = re.search(
            '(ProjetodeLei|ProjLei)'
            '(nº)?(\d+)\-?\w?(/|,de|de)(\d+)',
            clean_s)
    elif law_type == 'lei_comp':
        m = re.search(
            '(ProjetodeLei|ProjLei)Complementar'
            '(nº)?(\d+)\-?\w?(/|,de|de|)(\d+)',
            clean_s)
    elif law_type == 'decreto':
        m = re.search(
            '(ProjetodeDecretoLegislativo|ProjDecretoLegislativo)'
            '(nº)?(\d+)\-?\w?(/|,de|de|)(\d+)',
            clean_s)
    elif law_type == 'emenda':
        m = re.search(
            '(ProjetodeEmendaàLeiOrgânica|PropostadeEmenda)'
            '(nº)?(\d+)\-?\w?(/|,de|de|)(\d+)',
            clean_s)
    else:
        m = None
    if m:
        nr = m.group(3).zfill(4)
        ano = m.group(5)
        return '{}/{}'.format(nr, ano)
    return ''

def get_cpf(nm, depara):
    is_name = depara['nome_camara'] == clean_author_name(nm)
    if np.any(is_name):
        return depara[is_name]['cpf'].iloc[0]

USAGE_STRING = """
    usage: python integrate_data.py TYPE PROJETOS_FILES LEI_FILES
    
    TYPE needs to be 'lei', 'lei_comp', 'decreto' or 'emenda'

    PROJETOS_FILES and LEI_FILES may be comprised of several CSVs,
    separated by commas:

    python integrate_data.py projetos1.csv,projetos2.csv leis.csv
"""

SUPPORTED_TYPES = ['lei', 'lei_comp', 'decreto', 'emenda']

if len(sys.argv) < 3 or TYPE not in SUPPORTED_TYPES:
    print(USAGE_STRING)
    sys.exit(1)

START_YEAR = 2009
TYPE = sys.argv[1]
PROJETOS_FILES = sys.argv[2].split(',')
LEI_FILES = sys.argv[3].split(',')

config = AutoConfig(search_path='.')
POSTGRES_USER = config('POSTGRES_USER')
POSTGRES_HOST = config('POSTGRES_HOST')
POSTGRES_PORT = config('POSTGRES_PORT')
POSTGRES_DB = config('POSTGRES_DB')

# Get projetos de lei
projetos = []
for pf in PROJETOS_FILES:
    projetos.append(pd.read_csv(pf, ';'))
projetos = pd.concat(projetos)

projetos.dropna(subset=['ementa', 'autor'], inplace=True)
projetos.drop_duplicates(subset=['lei', 'data_publicacao'], inplace=True)

projetos['nr_lei'] = projetos['lei'].apply(lambda x: x.split('/')[0])
projetos['ano'] = projetos['lei'].apply(lambda x: x.split('/')[1])

projetos[projetos['ano'].astype(int) >= START_YEAR]

projetos.sort_values(['ano', 'nr_lei'], ascending=False, inplace=True)
projetos.drop(['nr_lei', 'ano'], axis=1, inplace=True)

projetos = projetos.rename({'lei': 'projeto'}, axis=1)

# Get leis
leis = []
for lf in LEI_FILES:
    leis.append(pd.read_csv(lf, ';'))
leis = pd.concat(leis)

leis['nr_projeto'] = leis['inteiro_teor'].apply(
    extract_projeto, law_type=TYPE)

# Merge leis with their respective projetos
dfm = projetos.merge(
    leis[['lei', 'ano', 'status', 'nr_projeto']].astype(str),
    how='left',
    left_on='projeto',
    right_on='nr_projeto')
dfm['status'] = dfm['status'].fillna('Não se aplica')
dfm = dfm.drop(['nr_projeto'], axis=1)

# Get CPF from vereadores using depara
engine = create_engine(
    f'postgresql://{POSTGRES_USER}@{POSTGRES_HOST}'
    f':{POSTGRES_PORT}/{POSTGRES_DB}')
depara = pd.read_sql(
    'SELECT * FROM eleitoral.depara_vereadores_camara_tse',
    engine)

dfm['cpfs'] = dfm['autor'].apply(
    lambda x: ",".join(list(
        filter(
            lambda x: x is not None,
            [get_cpf(nm, depara) for nm in x.split(',')]
        )
    ))
)

# Save integrated data to postgres
if TYPE == 'lei':
   dfm.to_sql(
       'projetos_lei_ordinaria',
       engine,
       schema='eleitoral',
       index=False)
if TYPE == 'lei_comp':
   dfm.to_sql(
       'projetos_lei_complementar',
       engine,
       schema='eleitoral',
       index=False)
if TYPE == 'decreto':
   dfm.to_sql(
       'projetos_decreto',
       engine,
       schema='eleitoral',
       index=False)
if TYPE == 'emenda':
   dfm.to_sql(
       'projetos_emenda_lei_organica',
       engine,
       schema='eleitoral',
       index=False)