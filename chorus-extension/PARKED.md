# Note on where this lives

Chorus is an unrelated project to the calcium score calculator that surrounds
it. It is parked in this repository, on a feature branch, only because it had
nowhere else to go: creating a new GitHub repository was blocked by token
scope, and the build container is ephemeral, so the alternative was losing the
work.

## Moving it to its own repository

It is entirely self-contained in this directory and has no ties to the parent
repo. To give it a proper home:

```bash
# 1. Create an empty repo on GitHub, e.g. cbaduboateng/chorus-extension
# 2. Then:
git clone <this repo> tmp && cd tmp
git checkout claude/idea-development-9c1n91
cd chorus-extension
rm PARKED.md
git init -b main
git add -A
git commit -m "Chorus: detect coordinated reply campaigns in comment sections"
git remote add origin git@github.com:cbaduboateng/chorus-extension.git
git push -u origin main
```

Then delete this directory from the calcium repo branch.
