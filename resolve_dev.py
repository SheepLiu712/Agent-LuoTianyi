"""Resolve merge conflicts with upstream/dev — keeps HEAD side."""
import os

script_dir = os.path.dirname(os.path.abspath(__file__))

# Get list of conflicted files from git
for root, dirs, files in os.walk(script_dir):
    # Skip .git
    if '.git' in dirs:
        dirs.remove('.git')
    if 'node_modules' in dirs:
        dirs.remove('node_modules')
    if 'mineflayer' in dirs:
        dirs.remove('mineflayer')

for root, dirs, files in os.walk(script_dir):
    for fname in files:
        fpath = os.path.join(root, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        changes = False
        while True:
            start = content.find('<<<<<<< HEAD\n')
            if start == -1:
                break
            sep = content.find('\n=======\n', start)
            end_marker = content.find('\n>>>>>>> ', sep if sep != -1 else start)
            if sep == -1 or end_marker == -1:
                print(f"Malformed conflict in {fname} at {start}")
                break
            eol = content.find('\n', end_marker + 1)
            if eol == -1:
                eol = len(content)
            else:
                eol = eol + 1

            head = content[start + len('<<<<<<< HEAD\n'):sep]
            upstream = content[sep + len('\n=======\n'):end_marker]

            if head.strip() == '' and upstream.strip() == '':
                content = content[:start] + content[eol:]
            else:
                content = content[:start] + head + content[eol:]
            changes = True

        if changes:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Resolved conflicts in {fname}")

# Verify no remaining markers
print("\n=== Verification ===")
remaining = 0
for root, dirs, files in os.walk(script_dir):
    if '.git' in dirs:
        dirs.remove('.git')
    if 'node_modules' in dirs:
        dirs.remove('node_modules')
    if 'mineflayer' in dirs:
        dirs.remove('mineflayer')
    for fname in files:
        fpath = os.path.join(root, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                c = f.read()
        except Exception:
            continue
        markers = c.count('<<<<<<<') + c.count('>>>>>>>') + c.count('=======')
        if markers > 0:
            # Check if it's just ==== in comments (like ==== section dividers)
            # Real conflict markers always have <<<<<<< or >>>>>>>
            if '<<<<<<<' in c or '>>>>>>>' in c:
                print(f"WARNING: {fpath} still has conflict markers!")
                remaining += 1

if remaining == 0:
    print("All conflicts resolved successfully!")
