"""Universal conflict resolver: keeps HEAD side for all conflicts."""
import os, sys

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)

for relative_path in ['README.md', 'server/src/plugins/music/singing_manager.py']:
    full_path = os.path.join(project_dir, relative_path)
    if not os.path.exists(full_path):
        continue
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()

    changes = False
    while True:
        start = content.find('<<<<<<< HEAD\n')
        if start == -1:
            break
        sep = content.find('\n=======\n', start)
        end_marker = content.find('\n>>>>>>> upstream/master', sep if sep != -1 else start)
        if sep == -1 or end_marker == -1:
            print(f"Malformed conflict in {relative_path} at {start}")
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
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Resolved conflicts in {relative_path}")
    else:
        print(f"No conflicts in {relative_path}")

# Verify
for relative_path in ['README.md', 'server/src/plugins/music/singing_manager.py']:
    full_path = os.path.join(project_dir, relative_path)
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            c = f.read()
        markers = c.count('<<<<<<<') + c.count('>>>>>>>') + c.count('=======')
        if markers > 0:
            print(f"WARNING: {relative_path} still has {markers} conflict markers!")
