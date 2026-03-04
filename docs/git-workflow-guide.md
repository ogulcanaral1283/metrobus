# 🔧 Git Workflow Guide — Metrobus Project

## For the Project Manager (You)

---

## 📋 Table of Contents

1. [Git Command Explanations (Token by Token)](#1-git-command-explanations-token-by-token)
2. [Branch Strategy](#2-branch-strategy)
3. [Giving Developers Access to Specific Packages](#3-giving-developers-access-to-specific-packages)
4. [Daily Git Commands Cheat Sheet](#4-daily-git-commands-cheat-sheet)
5. [Reviewing & Merging Pull Requests](#5-reviewing--merging-pull-requests)
6. [Conflict Resolution](#6-conflict-resolution)

---

## 1. Git Command Explanations (Token by Token)

### 🔹 `git clone https://github.com/ogulcanaral1283/metrobus.git`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `clone` | Copy a remote repository to your local machine |
| `https://...metrobus.git` | The URL of the repository on GitHub |

> **Result:** Creates a `metrobus/` folder on your computer with all the code.

---

### 🔹 `git clone --no-checkout https://github.com/ogulcanaral1283/metrobus.git`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `clone` | Copy the remote repository |
| `--no-checkout` | Download the repo history but **DON'T extract the files yet**. This lets you choose which folders to show before downloading them |
| `https://...metrobus.git` | The repo URL |

> **Result:** Creates `metrobus/` folder with only `.git/` inside — no source files yet.

---

### 🔹 `git sparse-checkout init --cone`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `sparse-checkout` | A feature that lets you pick **which folders** to show from the repo |
| `init` | Initialize (turn on) the sparse-checkout feature |
| `--cone` | Use "cone mode" — a simpler and faster mode where you select entire folders (not individual files) |

> **Result:** Sparse checkout is now active. Next you tell it which folders you want.

---

### 🔹 `git sparse-checkout set packages/dashboard packages/shared`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `sparse-checkout` | The folder-selection feature |
| `set` | Define which folders to include |
| `packages/dashboard` | First folder: the dashboard package |
| `packages/shared` | Second folder: the shared utilities (needed as a dependency) |

> **Result:** Only `packages/dashboard/` and `packages/shared/` will be visible. Everything else is hidden.

---

### 🔹 `git checkout develop`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `checkout` | Switch to a different branch (version of the code) |
| `develop` | The name of the branch to switch to |

> **Result:** Your working files now show the `develop` branch code (only the sparse-checkout folders).

---

### 🔹 `git checkout -b feature/my-feature`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `checkout` | Switch branches |
| `-b` | **Create** a new branch (if it doesn't exist) |
| `feature/my-feature` | The name of the new branch |

> **Result:** A new branch is created and you're switched to it. Your changes won't affect `develop` until you merge.

---

### 🔹 `git add .`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `add` | Stage files (prepare them to be saved/committed) |
| `.` | All changed files in the current directory (the dot means "everything here") |

> **Result:** All your changes are now "staged" — ready to be committed.

---

### 🔹 `git commit -m "feat: add map zoom"`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `commit` | Save the staged changes as a snapshot (a checkpoint in history) |
| `-m` | The following text is the commit message |
| `"feat: add map zoom"` | A short description of what you changed |

> **Result:** Your changes are saved locally with a message describing what you did.

---

### 🔹 `git push origin feature/my-feature`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `push` | Upload your local commits to the remote server (GitHub) |
| `origin` | The name of the remote server (GitHub). "origin" is the default name |
| `feature/my-feature` | The branch name to push |

> **Result:** Your branch and commits are now on GitHub, visible to everyone.

---

### 🔹 `git push -u origin main`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `push` | Upload to remote |
| `-u` | Set this remote branch as the **upstream** (default tracking). After this, you can just type `git push` without specifying origin and branch |
| `origin` | The remote server (GitHub) |
| `main` | The branch to push |

> **Result:** Pushes to GitHub AND sets up tracking so future `git push` commands are shorter.

---

### 🔹 `git pull origin develop`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `pull` | Download latest changes from remote AND merge them into your current branch |
| `origin` | The remote server |
| `develop` | The remote branch to pull from |

> **Result:** Your local code is updated with the latest changes from the team.

---

### 🔹 `git merge develop`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `merge` | Combine another branch's changes into your current branch |
| `develop` | The branch to merge FROM |

> **Result:** All changes from `develop` are now in your current branch (e.g., `main`).

---

### 🔹 `git status`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `status` | Show what files have been changed, staged, or are untracked |

> **Result:** A summary of your current working state.

---

### 🔹 `git log --oneline -10`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `log` | Show commit history |
| `--oneline` | Show each commit as a single line (compact) |
| `-10` | Show only the last 10 commits |

> **Result:** A compact list of the last 10 commits.

---

### 🔹 `git branch -a`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `branch` | List or manage branches |
| `-a` | Show **all** branches (local + remote) |

> **Result:** A list of every branch in the project.

---

### 🔹 `git branch -d feature/my-feature`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `branch` | Branch management |
| `-d` | **Delete** a branch (only if it has been merged) |
| `feature/my-feature` | The branch to delete |

> **Result:** The old branch is cleaned up after its work has been merged.

---

### 🔹 `git diff develop..main`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `diff` | Show differences between two things |
| `develop..main` | Compare branch `develop` with branch `main`. The `..` means "what changed between these two" |

> **Result:** Shows every line that is different between the two branches.

---

### 🔹 `git remote add origin https://github.com/ogulcanaral1283/metrobus.git`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `remote` | Manage remote server connections |
| `add` | Add a new remote |
| `origin` | The nickname for this remote (convention: "origin" = main repo) |
| `https://...metrobus.git` | The URL of the remote repository |

> **Result:** Your local repo now knows where to push/pull code from.

---

### 🔹 `git branch -M main`

| Token | Meaning |
|-------|---------|
| `git` | Run the Git program |
| `branch` | Branch management |
| `-M` | **Rename** the current branch (force, even if the name already exists) |
| `main` | The new name for the branch |

> **Result:** Your default branch is renamed from `master` to `main`.

---

## 2. Branch Strategy

```
main            ← Production-ready code (only YOU merge here)
  └── develop   ← Integration branch (team merges here via PR)
       ├── feature/dashboard-map     ← Developer A
       ├── feature/decision-engine   ← Developer B
       └── feature/realtime-engine   ← Developer C
```

| Rule | Description |
|------|-------------|
| **main** | Protected — only project manager merges |
| **develop** | Team integration — PRs go here |
| **feature/*** | Each developer creates their own branch |
| Never push to main directly | Always use Pull Requests |

---

## 3. Giving Developers Access to Specific Packages

Each developer runs these commands to see ONLY their package:

### Developer A — Dashboard
```bash
git clone --no-checkout https://github.com/ogulcanaral1283/metrobus.git
cd metrobus
git sparse-checkout init --cone
git sparse-checkout set packages/dashboard packages/shared
git checkout develop
npm install
```

### Developer B — Decision Engine
```bash
git clone --no-checkout https://github.com/ogulcanaral1283/metrobus.git
cd metrobus
git sparse-checkout init --cone
git sparse-checkout set packages/decision-engine packages/shared
git checkout develop
npm install
```

### Developer C — Realtime Engine
```bash
git clone --no-checkout https://github.com/ogulcanaral1283/metrobus.git
cd metrobus
git sparse-checkout init --cone
git sparse-checkout set packages/realtime-engine packages/shared
git checkout develop
npm install
```

---

## 4. Daily Git Commands Cheat Sheet

| I want to... | Command |
|--------------|---------|
| See current status | `git status` |
| Get latest changes | `git pull origin develop` |
| Create a new branch | `git checkout -b feature/my-feature` |
| Switch branches | `git checkout branch-name` |
| Save my changes | `git add .` → `git commit -m "message"` |
| Push to GitHub | `git push origin branch-name` |
| See commit history | `git log --oneline -10` |
| See all branches | `git branch -a` |
| Delete a branch | `git branch -d branch-name` |
| Merge a branch | `git merge branch-name` |

---

## 5. Reviewing & Merging Pull Requests

1. Developer pushes their branch → Creates **Pull Request** on GitHub
2. You go to **Pull Requests** tab on GitHub
3. Click on the PR → Review **Files changed**
4. Add comments if needed
5. Click **Approve** or **Request changes**
6. When approved → Click **Merge pull request** → Choose **Squash and merge**
7. Delete the feature branch

### Commit Message Convention
| Prefix | Usage |
|--------|-------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation |
| `style:` | CSS/formatting |
| `refactor:` | Code restructure |

---

## 6. Conflict Resolution

When two developers edit the same file:

```bash
git checkout develop
git pull origin develop
git merge feature/conflicting-branch

# Git shows conflicts like:
# <<<<<<< HEAD
# your code
# =======
# their code
# >>>>>>> feature/conflicting-branch

# Edit the file, keep what's correct, then:
git add .
git commit -m "fix: resolve merge conflict"
git push origin develop
```
