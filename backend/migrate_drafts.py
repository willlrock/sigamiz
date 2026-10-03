"""Import legacy bot_sessions.json without overwriting current database drafts."""
import argparse
import json
import re
from pathlib import Path
from backend.db import get_db
from backend.migrations import init_db


def migrate(source,apply=False):
    sessions=json.loads(Path(source).read_text(encoding='utf-8-sig'))
    if not isinstance(sessions,dict):
        raise ValueError('Legacy drafts must be a JSON object')
    init_db()
    conn=get_db();count=0
    try:
        for key,payload in sessions.items():
            if not re.fullmatch(r'-?\d+:\d+',key) or not isinstance(payload,dict):
                continue
            if conn.execute('SELECT 1 FROM bot_drafts WHERE draft_key=?',(key,)).fetchone():
                continue
            if apply:
                data={k:v for k,v in payload.items() if not k.startswith('web_login')}
                result=conn.execute('INSERT OR IGNORE INTO bot_drafts (draft_key,payload) VALUES (?,?)',(key,json.dumps(data,ensure_ascii=False)))
                count+=result.rowcount
            else:
                count+=1
        conn.commit()
        return count
    except Exception:
        conn.rollback();raise
    finally:
        conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(f'{"Imported" if args.apply else "Ready to import"}: {migrate(args.source,args.apply)}')
