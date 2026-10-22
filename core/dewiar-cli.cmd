@echo off
rem Installed Dewiar CLI: bundled Python, no UI or model startup.
if not exist "%~dp0..\..\python\python.exe" (
  echo Python Dewiar not found. Run diagnostic_cli.py with Python 3.12 from the local source checkout.
  exit /b 2
)
"%~dp0..\..\python\python.exe" -X utf8 -B "%~dp0diagnostic_cli.py" %*
exit /b %errorlevel%
