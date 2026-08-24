Set WshShell = CreateObject("WScript.Shell")
' Imposta la cartella di lavoro corrente sul percorso del progetto
WshShell.CurrentDirectory = "C:\Users\matte\scripts\02_musica_multimedia\crosswave_hybrid"

' Avvia il server python in background (0 = finestra nascosta)
WshShell.Run "python app.py", 0, False

' Attendi 2 secondi che il server si avvii
WScript.Sleep 2000

' Apri automaticamente il browser all'indirizzo di Crossplayer
WshShell.Run "http://localhost:5002"
