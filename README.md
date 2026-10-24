# gcore-runners

Public GitHub-runner jobs for GorbunCore, a personal Claude Code setup: checks and builds that run in the cloud
instead of on the owner's machines. Everything here is public by design.

## What belongs here
- generic code checks (shell syntax, JSON, plist, link checks);
- builds and tests of plugins and small tools;
- heavy one-off jobs that need no personal data.

## What must never be committed
Secrets and tokens, personal or health data, chat identifiers, user names and home paths, logs from the owner's machines.
The `guard` workflow rejects obvious patterns on every push; a stricter private check runs on the owner's server before anything is uploaded.

## How it is used
The owner's server starts a workflow (`gh workflow run`) and reads results from the `results` branch.
Usage is kept modest and within GitHub's Terms of Service.
