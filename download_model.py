import sys, time
from nobodywho import download_model, get_cached_models
from journal.engine import DEFAULT_MODEL

print("cached before:", get_cached_models())
last = [0.0]
def progress(done, total):
    now = time.time()
    if now - last[0] > 3 or done == total:
        last[0] = now
        pct = (done / total * 100) if total else 0
        print(f"  {done/1e6:.0f} / {total/1e6:.0f} MB  ({pct:.1f}%)", flush=True)

path = download_model(DEFAULT_MODEL, on_download_progress=progress)
print("DONE ->", path)
