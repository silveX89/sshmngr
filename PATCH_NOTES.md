# PATCH_NOTES – exp autosuggest + Bash completion

## Summary
- Removed numeric menu requirement; added interactive fuzzy autosuggest.
- Added `--list-hosts` for shell completion and tooling.
- Delivered a Bash completion script for quick host completion.

## Files to replace / add
Replace:
- `sshmngr/sshmngr.py`

Add:
- `completions/sshmngr.bash`
- `requirements.txt` (or add `prompt_toolkit>=3.0.43` to your existing file)
- `README.md` (section describing new features)

## Post-merge steps
- `pip install prompt_toolkit>=3.0.43`
- Source the completion script (see README).

## Backout plan
Revert the file(s) above to the previous commit on your exp branch if needed.
