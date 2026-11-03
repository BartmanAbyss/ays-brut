"""Deploy: build the intro and put the release files into release/.

    python build/deploy.py

Runs build/build.py, stops if the entry is over the 8 192-byte budget, then copies
    build/intro.cmd          -> release/ays-brut.cmd               (the compo entry, Windows)
    build/intro-compat.html  -> release/ays-brut.uncompressed.html (any OS, any WebGPU browser)
release/ is tracked: commit it after a deploy. It is marked binary in .gitattributes - the
.cmd ends in raw brotli bytes, and a line-ending conversion would break it. The dropper
reads itself by its own path (%~f0), so the name does not matter to it.
"""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
OUT = os.path.join(REPO, 'release')
BUDGET = 8192
FILES = [('intro.cmd', 'ays-brut.cmd'), ('intro-compat.html', 'ays-brut.uncompressed.html')]


def main():
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'build.py')], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stdout.write(r.stdout[-3000:]); sys.stderr.write(r.stderr[-3000:])
        sys.exit('DEPLOY FAILED: the build failed')
    cmd = os.path.join(ROOT, 'intro.cmd')
    n = os.path.getsize(cmd)
    if n > BUDGET:
        sys.exit('DEPLOY FAILED: intro.cmd is %d bytes, %d over the %d budget' % (n, n - BUDGET, BUDGET))
    os.makedirs(OUT, exist_ok=True)
    for src, dst in FILES:
        shutil.copyfile(os.path.join(ROOT, src), os.path.join(OUT, dst))
        print('release/%-28s %7d bytes' % (dst, os.path.getsize(os.path.join(OUT, dst))))
    print('deployed: %d bytes, %d under the budget - commit release/' % (n, BUDGET - n))


if __name__ == '__main__':
    main()
