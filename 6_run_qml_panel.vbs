Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root

launcher = root & "\run_panel_hidden.pyw"
If Not fso.FileExists(launcher) Then
    MsgBox "run_panel_hidden.pyw not found:" & vbCrLf & launcher, vbCritical, "Neko QML"
    WScript.Quit 1
End If

If fso.FileExists("C:\Windows\pyw.exe") Then
    cmd = """C:\Windows\pyw.exe"" -3 """ & launcher & """"
Else
    cmd = "pythonw.exe """ & launcher & """"
End If

shell.Run cmd, 0, False
