Option Explicit

Dim shell, fso, root, launcher, pyw, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root

If Not IsAdministrator() Then
    RelaunchAsAdministrator root
    WScript.Quit 0
End If

launcher = fso.BuildPath(root, "run_panel_hidden.pyw")
If Not fso.FileExists(launcher) Then
    MsgBox "run_panel_hidden.pyw not found:" & vbCrLf & launcher, vbCritical, "Neko QML"
    WScript.Quit 1
End If

pyw = fso.BuildPath(shell.ExpandEnvironmentStrings("%WINDIR%"), "pyw.exe")
If fso.FileExists(pyw) Then
    cmd = QuoteArg(pyw) & " -3 " & QuoteArg(launcher)
Else
    cmd = "pythonw.exe " & QuoteArg(launcher)
End If

shell.Run cmd, 0, False

Function IsAdministrator()
    Dim rc, comspec

    On Error Resume Next
    Err.Clear
    shell.RegRead "HKEY_USERS\S-1-5-19\Environment\TEMP"
    If Err.Number = 0 Then
        IsAdministrator = True
        On Error GoTo 0
        Exit Function
    End If

    Err.Clear
    comspec = shell.ExpandEnvironmentStrings("%ComSpec%")
    rc = shell.Run(QuoteArg(comspec) & " /c net session >nul 2>&1", 0, True)
    IsAdministrator = (Err.Number = 0 And rc = 0)
    Err.Clear
    On Error GoTo 0
End Function

Sub RelaunchAsAdministrator(ByVal workingDir)
    Dim app

    On Error Resume Next
    Err.Clear
    Set app = CreateObject("Shell.Application")
    app.ShellExecute WScript.FullName, QuoteArg(WScript.ScriptFullName), workingDir, "runas", 1
    If Err.Number <> 0 Then
        MsgBox "Administrator permission is required to start Neko QML." & vbCrLf & Err.Description, vbCritical, "Neko QML"
        WScript.Quit 1
    End If
    On Error GoTo 0
End Sub

Function QuoteArg(ByVal value)
    QuoteArg = Chr(34) & value & Chr(34)
End Function
