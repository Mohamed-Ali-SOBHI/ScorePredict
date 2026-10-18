"""Download an encrypted report and decrypt it only on the owner's computer."""
from __future__ import annotations
import io
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

from production import observation_export as ex

HOME=ex.ROOT.parent/'suivi_prive_9'
KEY=HOME/'.private/observation_key.pem'
OUTPUT=HOME/'italie_angleterre.json'
ARTIFACT='private-italy-epl-encrypted'


def fetch():
    if not KEY.exists():raise ValueError('La clé privée locale est absente.')
    repo='repos/Mohamed-Ali-SOBHI/ScorePredict'
    response=json.loads(subprocess.check_output(['gh','api',repo+'/actions/artifacts?name='+ARTIFACT+'&per_page=30'],cwd=ex.ROOT))
    candidates=[a for a in response['artifacts'] if a['name']==ARTIFACT and not a['expired']]
    if not candidates:raise ValueError('Aucune collecte privée chiffrée disponible.')
    artifact=max(candidates,key=lambda a:a['created_at'])
    archive=subprocess.check_output(['gh','api',repo+'/actions/artifacts/'+str(artifact['id'])+'/zip'],cwd=ex.ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        names=[n for n in zipped.namelist() if n.endswith('private-observation.encrypted.json')]
        if len(names)!=1:raise ValueError('Rapport privé chiffré ambigu.')
        encrypted=zipped.read(names[0])
    with tempfile.TemporaryDirectory(prefix='private-observation-') as temp:
        cipher=Path(temp)/'encrypted.json';plain=Path(temp)/'decrypted.json'
        cipher.write_bytes(encrypted)
        subprocess.run(['node',str(ex.ROOT/'production/private_observation_crypto.cjs'),'decrypt',
            '--input',str(cipher),'--private-key',str(KEY),'--output',str(plain)],check=True,cwd=ex.ROOT)
        data=json.loads(plain.read_text(encoding='utf8'))
    if data.get('schemaVersion')!=1 or data.get('private') is not True:raise ValueError('Rapport privé invalide.')
    ex.atomic_write(OUTPUT,data)
    return data


def load_latest():
    try:return fetch()
    except Exception:
        return {'status':'unavailable','message':'Italie/Angleterre : la dernière collecte privée ne peut pas être vérifiée.'}
