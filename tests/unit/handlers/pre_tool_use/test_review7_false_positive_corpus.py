"""False-positive corpus for Plan 00466 guard-defects review 7.

Every fix in review 7 (MAJOR-1 through MAJOR-5, MINOR-1, MINOR-2) widens what
``SecretFileGuardHandler`` recurses into or recognises as a wrapper/
interpreter/one-liner shape. The risk symmetric to a fail-open is a NEW
false positive: an everyday developer command that now gets denied because
it happens to LOOK like one of the newly-recognised shapes (a wrapper name,
an interpreter one-liner, a process substitution, a `$(...)`).

This file pins a corpus of 150+ everyday commands -- git, npm/docker/kubectl,
ssh/curl/wget, shell completions, `eval "$(ssh-agent -s)"`, printf/echo -e,
heredocs, ordinary `python3 -c`/`node -e`/`ruby -e` one-liners, `sudo`/`env`/
`timeout`/`nice` wrapping ordinary (non-shell) commands, process substitution
in `diff`/`comm`, and plain pipes -- that must all stay ALLOWED.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)


def _hook_input(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _handler() -> SecretFileGuardHandler:
    return SecretFileGuardHandler()


# fmt: off
EVERYDAY_COMMANDS: list[str] = [
    # --- git ---
    "git status",
    "git add -A",
    "git commit -m 'fix: correct the off-by-one in the paginator'",
    "git log --oneline -20",
    "git diff HEAD~1",
    "git push origin main",
    "git fetch --all --prune",
    "git checkout -b feature/new-thing",
    "git rebase -i HEAD~5",
    "git stash list",
    "git blame src/app.py",
    "git clone https://github.com/example/repo.git",
    "git remote -v",
    "git tag -a v1.2.3 -m 'release'",
    "git submodule update --init --recursive",
    # --- package managers ---
    "npm install",
    "npm run build",
    "npm test -- --watch",
    "npx eslint . --fix",
    "yarn add react react-dom",
    "pip install -r requirements.txt",
    "pip install --user black",
    "poetry install",
    "cargo build --release",
    "cargo test",
    "go build ./...",
    "go test ./... -v",
    "composer install",
    "bundle install",
    "gem install rails",
    # --- docker / kubernetes ---
    "docker build -t myapp:latest .",
    "docker run -p 8080:80 myapp:latest",
    "docker compose up -d",
    "docker ps -a",
    "docker logs -f mycontainer",
    "kubectl get pods -n default",
    "kubectl apply -f deployment.yaml",
    "kubectl logs -f mypod --since=1h",
    "kubectl exec -it mypod -- ls /app",
    "helm install myrelease ./chart",
    # --- ssh / network ---
    "ssh user@example.com",
    "ssh -p 2222 deploy@server 'systemctl restart myapp'",
    "ssh-add -l",
    "ssh-keygen -t ed25519 -C 'me@example.com'",
    "scp file.txt user@host:/tmp/",
    "rsync -avz ./dist/ user@host:/var/www/",
    "curl -s https://api.example.com/health",
    "curl -X POST https://api.example.com/items -d '{\"name\":\"x\"}'",
    "curl -fsSL https://example.com/install.sh -o install.sh",
    "wget https://example.com/archive.tar.gz",
    "wget -O out.json https://api.example.com/data",
    "ping -c 4 example.com",
    "nslookup example.com",
    "dig +short example.com",
    # --- shell completions / eval idioms ---
    "source <(kubectl completion bash)",
    "source <(gh completion -s bash)",
    "source <(helm completion bash)",
    "eval \"$(ssh-agent -s)\"",
    "eval \"$(pip completion --bash)\"",
    "eval \"$(direnv hook bash)\"",
    "eval \"$(pyenv init -)\"",
    "eval \"$(rbenv init -)\"",
    'eval "$(gh completion -s zsh)"',
    # --- printf / echo / heredocs ---
    "echo 'hello world'",
    "echo -e 'line one\\nline two'",
    "printf '%s\\n' 'hello'",
    "printf 'name=%s age=%d\\n' Alice 30",
    "cat <<'EOF'\nsome literal text\nEOF",
    "cat <<EOF\nvariable: $HOME\nEOF",
    "tee /tmp/out.txt <<< 'some content'",
    # --- ordinary interpreter one-liners (no shell-exec call inside) ---
    "python3 -c \"print('hello world')\"",
    "python3 -c \"import sys; print(sys.version)\"",
    "python3.12 -c \"print(1 + 1)\"",
    "python3 -I -c \"print('isolated')\"",
    "pypy3 -c \"print('fast')\"",
    "node -e \"console.log('hello')\"",
    "node -p \"1 + 1\"",
    "node --eval \"console.log(process.version)\"",
    "ruby -e \"puts 'hello world'\"",
    "ruby -we \"puts 1 + 1\"",
    "perl -e \"print 'hello world\\n'\"",
    "perl -E \"say 'hello'\"",
    "perl -le \"print 42\"",
    "php -r \"echo 'hello world';\"",
    # --- sudo / env / timeout / nice wrapping ORDINARY commands ---
    "sudo apt update",
    "sudo apt-get install -y build-essential",
    "sudo -u deploy ls -la /srv",
    "sudo -u www-data whoami",
    "sudo systemctl restart nginx",
    "env FOO=bar node server.js",
    "env -i PATH=/usr/bin ls",
    "timeout 30 npm test",
    "timeout 5 curl -s https://example.com",
    "nice -n 10 make -j4",
    "nice -n 19 ./long_running_script.sh",
    "nohup ./server &",
    "stdbuf -oL grep pattern file.txt",
    "ionice -c3 rsync -a src/ dst/",
    # --- pipes to non-shell commands ---
    "cat access.log | grep 404",
    "ps aux | grep python",
    "history | grep git",
    "docker ps | awk '{print $1}'",
    "ls -la | sort",
    "find . -name '*.py' | xargs wc -l",
    "cat file.txt | sort | uniq -c",
    "echo hello | tr a-z A-Z",
    "curl -s https://example.com | jq '.data'",
    # --- process substitution in ordinary diff/comm usage ---
    "diff <(sort file1.txt) <(sort file2.txt)",
    "comm -3 <(sort a.txt) <(sort b.txt)",
    "diff <(git show HEAD:file.py) <(git show HEAD~1:file.py)",
    # --- command substitution, ordinary ---
    "echo $(date +%Y-%m-%d)",
    "VERSION=$(git describe --tags)",
    "FILES=$(find . -name '*.md')",
    "echo \"Current branch: $(git branch --show-current)\"",
    "COUNT=$(ls -1 | wc -l)",
    # --- test / build tooling ---
    "pytest tests/ -v",
    "pytest tests/unit -k 'test_foo'",
    "make test",
    "make -j$(nproc) build",
    "tox -e py311",
    "eslint src/ --fix",
    "prettier --write .",
    "black .",
    "ruff check .",
    "mypy src/",
    # --- misc everyday shell ---
    "mkdir -p build/output",
    "rm -rf node_modules/.cache",
    "cp -r src/ backup/",
    "mv old_name.txt new_name.txt",
    "chmod +x deploy.sh",
    "touch .gitkeep",
    "df -h",
    "du -sh ./node_modules",
    "free -m",
    "uptime",
    "whoami",
    "pwd",
    "date",
    "uname -a",
    "which python3",
    "type node",
    "alias ll='ls -la'",
    "export PATH=$PATH:/usr/local/bin",
    "source ~/.bashrc",
    "source .venv/bin/activate",
    ". .venv/bin/activate",
    "export NODE_ENV=production",
    "unset DEBUG",
    "history -c",
    "jobs -l",
    "wait",
    "trap 'echo cleanup' EXIT",
    # --- watch / flock ordinary usage ---
    "watch -n 5 'kubectl get pods'",
    "watch --interval 2 date",
    "flock /tmp/mylock.lock echo done",
    # --- archives ---
    "tar -czvf archive.tar.gz ./dist",
    "tar -xzvf archive.tar.gz",
    "zip -r archive.zip ./dist",
    "unzip archive.zip -d ./out",
    "gzip -k file.txt",
    # --- database CLIs ---
    "psql -h localhost -U postgres -d mydb -c 'SELECT 1'",
    "mysql -u root -p mydb -e 'SHOW TABLES'",
    "redis-cli ping",
    "mongosh --eval 'db.stats()'",
    # --- misc network/file: URLs to non-protected paths ---
    "curl -s file:///etc/hostname",
    "curl file:///tmp/output.json",
    "git clone file:///home/user/local-repo /tmp/clone",
]
# fmt: on


class TestReview7FalsePositiveCorpus:
    """Every command above must stay ALLOWED after the review 7 fixes."""

    @pytest.mark.parametrize("command", EVERYDAY_COMMANDS, ids=range(len(EVERYDAY_COMMANDS)))
    def test_command_is_not_denied(self, command: str) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input(command)), command

    def test_corpus_has_at_least_150_commands(self) -> None:
        assert len(EVERYDAY_COMMANDS) >= 150, len(EVERYDAY_COMMANDS)
