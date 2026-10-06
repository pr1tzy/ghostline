' Starts Ghostline in the background (no window). Stop it with stop.bat.
' Before the first setup, or after an update, it opens start.bat instead so the setup can show its progress.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
current = False
If fso.FileExists(dir & "\.venv\installed-requirements.txt") Then
  current = (fso.OpenTextFile(dir & "\requirements.txt").ReadAll = fso.OpenTextFile(dir & "\.venv\installed-requirements.txt").ReadAll)
End If
If current And fso.FileExists(dir & "\.venv\Scripts\pythonw.exe") Then
  sh.Run """" & dir & "\.venv\Scripts\pythonw.exe"" """ & dir & "\run.py"" --no-browser", 0, False
Else
  sh.Run """" & dir & "\start.bat""", 1, False
End If
