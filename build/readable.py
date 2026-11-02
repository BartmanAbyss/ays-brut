"""Write build/stripped.wgsl: the shader the RELEASE runs, with comments and names kept.

Neither existing file answers "what does the release actually run, and why":

  dev/champagne.html   the names and the comments, and every debug branch, profiler
                       hook and dev-only block alongside them
  build/min.pretty.wgsl  exactly what ships, with every name packed to a letter or two
                       and every comment gone

This runs the release's own stripping passes - build.py's functions, not a copy of them -
over text in which the comments are MASKED rather than deleted, then puts them back. So
the dead branches, the debug toggles and the tree-shaken helpers are gone, and what is
left reads like the source it came from.

Run:  python build/readable.py
Out:  build/stripped.wgsl

Masking, not keeping: fold_branches works on text, and a comment that mentions `if (PROF)`
becomes `if (false)` after the profiler substitution and is folded AS CODE - that trap
deleted the glass constants once (CLAUDE.md, *Text-level folding must never see a
comment*). Here every comment is replaced by an inert `/*~12~*/` token first, which no
pass can misread, and restored at the end. A comment inside a branch that gets folded
away is never restored, which is the point.

What this is NOT: it is not what ships. The packer's renaming, `nameless_uniforms` and
`short_entries` are deliberately skipped, and wgslender's syntax rewrites are not applied
either - only its verdict on which declarations are dead. For the shipped text, read
build/min.pretty.wgsl.
"""
import io, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import build  # noqa: E402

OUT = os.path.join(ROOT, 'stripped.wgsl')


# ── comments as inert tokens ─────────────────────────────────────────────────────
# `/*~K~*/` survives every pass unchanged: it holds no brace, paren, semicolon, digit
# comparison or identifier, so fold_branches, _CMP, peephole and the chunk scanner below
# all walk straight past it. WGSL block comments nest, so the scanner tracks depth.
_TOK = re.compile(r'/\*~(\d+)~\*/')


def mask_comments(w):
    out, bodies, i, n = [], [], 0, len(w)
    while i < n:
        two = w[i:i + 2]
        if two == '//':
            j = w.find('\n', i)
            j = n if j < 0 else j
        elif two == '/*':
            depth, j = 1, i + 2
            while j < n and depth:
                if w[j:j + 2] == '/*':
                    depth += 1
                    j += 2
                elif w[j:j + 2] == '*/':
                    depth -= 1
                    j += 2
                else:
                    j += 1
        else:
            out.append(w[i])
            i += 1
            continue
        bodies.append(w[i:j])
        out.append('/*~%d~*/' % (len(bodies) - 1))
        i = j
    return ''.join(out), bodies


def restore_comments(w, bodies):
    """Put the bodies back. A line comment goes back as `//...` only where the rest of the
    line is empty: peephole's `x * 1.` rewrite eats the whitespace around the `*`, newline
    included, so a token CAN end up with code after it on one line - and restoring `//`
    there would comment that code out. Those few go back as `/* ... */`."""
    def rep(m):
        body = bodies[int(m.group(1))]
        tail = w[m.end():]
        if body.startswith('//') and not re.match(r'[ \t]*(\n|$)', tail):
            return '/* ' + body[2:].strip() + ' */'
        return body
    return _TOK.sub(rep, w)


def strip_comments(w):
    w = re.sub(r'/\*.*?\*/', '', w, flags=re.S)
    return re.sub(r'//[^\n]*', '', w)


# ── top-level declarations ───────────────────────────────────────────────────────
_DECL = re.compile(r'\b(?:fn|struct|const|alias|override|var)\s*(?:<[^>]*>)?\s*(\w+)')


def top_items(w):
    """[(name, start, end)] for every top-level declaration, in order. `start` includes the
    blank lines and comments that precede it, so deleting a dead function takes the comment
    that explains it with it."""
    items, i, n, start = [], 0, len(w), 0
    while i < n:
        while i < n and w[i].isspace():
            i += 1
        if i >= n:
            break
        j, depth, paren = i, 0, 0
        while j < n:
            c = w[j]
            if c == '(':
                paren += 1
            elif c == ')':
                paren -= 1
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            elif c == ';' and depth == 0 and paren == 0:
                j += 1
                break
            j += 1
        m = _DECL.search(w[i:j])
        items.append((m.group(1) if m else None, start, j))
        start = i = j
    return items


def survivors(w):
    """The names wgslender leaves standing. It is given the shader with the comments gone
    (its output drops them anyway) and only its verdict is used - never its text."""
    shaken, _ = build.tree_shake(strip_comments(w))
    return {n for n, _, _ in top_items(shaken) if n}, shaken


def build_readable(verbose=True):
    say = print if verbose else (lambda *a: None)
    src = build.read(build.SRC)
    wgsl = re.search(r'<script type="text/wgsl" id="wgsl-main">(.*?)</script>', src, re.S).group(1)
    js = re.search(r'<script type="module">(.*?)</script>', src, re.S).group(1)
    ui = build.spec_defaults(js)
    ui.update(build.UI_OVERRIDE)

    n0 = len(wgsl.encode())
    wgsl = build.cut_dev(wgsl)
    say('source           %7d bytes' % n0)
    say('//#D removed     %7d' % len(wgsl.encode()))

    wgsl, bodies = mask_comments(wgsl)
    say('comments masked  %7d tokens' % len(bodies))

    # the same order prepare() uses, on masked text instead of stripped text
    wgsl = re.sub(r'(?m)^override PROF[^\n]*\n', '', wgsl)
    wgsl = re.sub(r'\bPROF\b', 'false', wgsl)
    wgsl, folded = build.fold_uniforms(wgsl, ui)
    wgsl, branches = build.fold_branches(wgsl)
    wgsl, tidied = build.peephole(wgsl)
    say('uniforms folded  %7d references' % folded)
    say('branches folded  %7d ifs resolved' % branches)
    say('peephole         %7d leftovers' % tidied)

    live, _ = survivors(wgsl)
    items = top_items(wgsl)
    dead = [n for n, _, _ in items if n and n not in live]
    wgsl = ''.join(wgsl[a:b] for n, a, b in items if n is None or n in live)
    say('tree-shaken      %7d declarations dropped%s'
        % (len(dead), (': ' + ', '.join(sorted(dead))) if dead else ''))

    wgsl = restore_comments(wgsl, bodies)
    # A folded branch or a dropped profiler line leaves its indentation behind as a
    # whitespace-only line, which the blank-run collapse below only sees once the trailing
    # whitespace is gone.
    wgsl = re.sub(r'[ \t]+(?=\n)', '', wgsl)
    wgsl = re.sub(r'\n{3,}', '\n\n', wgsl)
    wgsl = re.sub(r'\{\n\n', '{\n', wgsl).strip() + '\n'

    # Does it still parse, and did we delete exactly what wgslender would? Both at once:
    # hand the result back to wgslender with its comments gone and ask again. A different
    # set means the chunk scanner and the shaker disagree about what a declaration is; a
    # BuildError from here means the restored text no longer parses.
    again, _ = survivors(wgsl)
    if again != live:
        raise build.BuildError('readable: declarations disagree after the round trip - '
                               'only in the output: %s; only in the shaken shader: %s'
                               % (sorted(again - live), sorted(live - again)))
    say('checked          wgslender parses it and finds nothing further to remove')

    head = ('// GENERATED by build/readable.py - do not edit. Regenerate:\n'
            '//     python build/readable.py\n'
            '//\n'
            '// The shader the release runs, with the source\'s names and comments kept.\n'
            '// %d bytes of harness WGSL -> %d: %d dead ifs folded, %d declarations dropped.\n'
            '// NOT what ships - no packing, no nameless uniforms, no short entry points.\n'
            '// For the shipped text see build/min.pretty.wgsl.\n\n'
            % (n0, len(wgsl.encode()), branches, len(dead)))
    return head + wgsl


def main():
    w = build_readable()
    tmp = OUT + '.tmp'
    # read, build, check, THEN write through a temporary file: `open(p,'w').write(f())`
    # truncates p before f() runs, and a generator that read its own output left the
    # harness at 0 bytes once (CLAUDE.md, *Editing safely*).
    io.open(tmp, 'wb').write(w.encode())
    os.replace(tmp, OUT)
    print('wrote            %7d bytes   %s' % (len(w.encode()), os.path.relpath(OUT, ROOT)))


if __name__ == '__main__':
    try:
        main()
    except build.BuildError as e:
        print('\nFAILED: %s' % e, file=sys.stderr)
        sys.exit(1)
