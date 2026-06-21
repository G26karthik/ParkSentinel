import gzip
import shutil
import os

in_path = 'data/jan_to_may_police_violation_anonymized791b166.csv'
out_path = 'data/jan_to_may_police_violation_anonymized791b166.csv.gz'

print(f"Compressing {in_path} to {out_path}...")
with open(in_path, 'rb') as f_in:
    with gzip.open(out_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
print("Compression complete!")
