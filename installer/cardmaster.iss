; ============================================================
;  CardMaster LS (Fahrerkarte) - Inno-Setup-Skript
;  Baut:  installer\Ausgabe\CardMaster-Setup-1.4.14.exe
;
;  Installation ohne Administrator-Rechte nach
;  %LOCALAPPDATA%\Programs\CardMaster LS
;  Eigene Dateien (Spesenzettel, .ddd, Abrechnungsstand) liegen in
;  Dokumente\CardMaster LS und bleiben bei einer Deinstallation erhalten.
;
;  Beim ersten Start uebernimmt das Programm den Datenordner der
;  Version 1.0 (Dokumente\Spesenzettel). Die alte Programm-Installation
;  "Spesenzettel" wird waehrend der Installation automatisch entfernt.
; ============================================================

#define AppName "CardMaster LS"
#define AppVersion "1.4.14"
#define AppPublisher "Standardprojekt"
#define AppExeName "CardMaster LS.exe"

[Setup]
AppId={{AA948BDF-9054-4989-86E1-0E34DED2FEFE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userpf}\CardMaster LS
DefaultGroupName=CardMaster LS
DisableProgramGroupPage=yes
; Installationsordner darf im Assistenten gewaehlt werden (auch bei Updates)
DisableDirPage=no
; Installation nur fuer den aktuellen Benutzer - keine Admin-Rechte noetig
PrivilegesRequired=lowest
OutputDir=Ausgabe
OutputBaseFilename=CardMaster-Setup-{#AppVersion}
SetupIconFile=cardmaster.ico
; Assistenten-Grafiken aus den Projekt-Assets (siehe installer_grafiken.py)
WizardImageFile=wizard_image.bmp
WizardSmallImageFile=wizard_small.bmp
WizardStyle=modern
; Deutsch als Assistentensprache
ShowLanguageDialog=no

[Languages]
Name: "ger"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
ger.LaunchApp=CardMaster LS jetzt starten
ger.DataNote=Hinweis: Abrechnungsstand und Einstellungen liegen in Dokumente\CardMaster LS und bleiben bei einer Deinstallation erhalten. Die Ordner für .ddd-Downloads und Spesenzettel-PDFs lassen sich im Programm im Reiter „Einstellungen“ ändern. Dateien aus der alten Version 1.0 (Dokumente\Spesenzettel) wurden beim ersten Start übernommen.

[Files]
Source: "dist\CardMaster LS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\CardMaster LS"; Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon
Name: "{group}\Deinstallieren"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\CardMaster LS"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Verknüpfungen:"; Flags: checkedonce
Name: "startmenuicon"; Description: "Startmenü-Eintrag erstellen"; GroupDescription: "Verknüpfungen:"; Flags: checkedonce

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; nur Programmordner entfernen, Dokumente\CardMaster LS bleibt erhalten

[Code]
const
  AlterAppOrdner = '{userpf}\Spesenzettel';
  AlterStartOrdner = '{userprograms}\Spesenzettel';
  AlterUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E4F1B67-9C3A-4D52-8F16-2A1C5B77E9A4}_is1';

procedure AlteVersionEntfernen();
begin
  // Version 1.0 ("Spesenzettel", alte App-Id) restlos entfernen:
  // Programmordner, Startmenue-Gruppe, Desktop-Verknuepfung und
  // den Eintrag unter "Apps & Features". Der Datenordner
  // Dokumente\Spesenzettel bleibt unberuehrt (wird beim ersten Start
  // von CardMaster LS uebernommen).
  DelTree(ExpandConstant(AlterAppOrdner), True, True, True);
  DelTree(ExpandConstant(AlterStartOrdner), True, True, True);
  DeleteFile(ExpandConstant('{autodesktop}\Spesenzettel.lnk'));
  RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, AlterUninstallKey);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    AlteVersionEntfernen();
    // Hinweis nur beim interaktiven Lauf zeigen; bei /SILENT und
    // /VERYSILENT wuerde die Box sonst das unbeaufsichtigte Installieren
    // blockieren.
    if not WizardSilent() then
      MsgBox(ExpandConstant('{cm:DataNote}'), mbInformation, MB_OK);
  end;
end;
