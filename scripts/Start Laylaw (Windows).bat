@echo off
rem Starts Laylaw on this computer only and opens it in the browser.
py -3 -m laylaw run
if errorlevel 1 pause
