Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = appDir & "\.venv\Scripts\pythonw.exe"
scriptPath = appDir & "\main.py"
shell.CurrentDirectory = appDir
shell.Run """" & pythonw & """ """ & scriptPath & """", 0, False
