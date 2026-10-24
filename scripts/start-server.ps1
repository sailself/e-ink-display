# Runs the dashboard server in the foreground (Ctrl+C to stop). Logs also go to logs/server.log.
$root = Split-Path -Parent $PSScriptRoot
python "$root\server\server.py"
