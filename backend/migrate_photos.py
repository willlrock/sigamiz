"""Copy legacy uploads to stable keys. Dry run by default; retain original files."""
import argparse
import io
from pathlib import Path
from PIL import Image, ImageOps
from backend.db import get_db
from backend.migrations import init_db
from backend.storage import UPLOAD_DIR, store_photo, delete_photo


def migrate(apply=False):
    init_db()
    root=Path(UPLOAD_DIR).resolve()
    conn=get_db()
    try:
        columns={row[1] for row in conn.execute('PRAGMA table_info(listing_photos)').fetchall()}
        path_columns=[column for column in ('file_path','photo_path') if column in columns]
        expression='COALESCE('+','.join(path_columns)+')' if len(path_columns)>1 else path_columns[0]
        rows=conn.execute(f'SELECT id,{expression} AS path FROM listing_photos').fetchall()
    finally:
        conn.close()
    migrated=missing=0
    for row in rows:
        value=str(row['path'] or '').replace('\\','/')
        if value.startswith(('photos/','https://','http://')):
            continue
        relative=value.split('/uploads/',1)[-1].lstrip('/')
        candidate=Path(value).resolve()
        source=candidate if candidate.is_relative_to(root) else (root/relative).resolve()
        if not source.is_relative_to(root) or not source.is_file() or source.suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):
            missing+=1
            continue
        if not apply:
            migrated+=1
            continue
        with Image.open(source) as image:
            image=ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1200,1200))
            encoded=io.BytesIO()
            image.save(encoded,format='JPEG',quality=85)
        key=store_photo(encoded.getvalue())
        conn=get_db()
        committed=False
        try:
            update=conn.execute('UPDATE listing_photos SET '+','.join(f'{column}=?' for column in path_columns)+f' WHERE id=? AND {expression}=?', [*[key]*len(path_columns),row['id'],row['path']])
            if update.rowcount==1:
                conn.commit();committed=True;migrated+=1
            else:
                conn.rollback()
        finally:
            conn.close()
            if not committed:
                delete_photo(key)
    return migrated,missing


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    arguments=parser.parse_args()
    count,missing=migrate(arguments.apply)
    print(f'{"Copied" if arguments.apply else "Ready to copy"}: {count}; unavailable legacy files: {missing}')
    raise SystemExit(2 if missing else 0)
