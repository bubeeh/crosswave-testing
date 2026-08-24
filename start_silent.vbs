Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\matte\scripts\02_musica_multimedia\crosswave_hybrid"
' Avvia in background senza finestra (0 = nascosto)
WshShell.Run "python app.py", 0, False
