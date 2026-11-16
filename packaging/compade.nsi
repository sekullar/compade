; Compade kurulum dosyası (NSIS 3). build.py çağırır: makensis -DVERSION=x.y.z -DSRC=<dist\Compade> -DOUT=<exe>
; Sessiz kurulum: Compade-Setup-x.y.z.exe /S /D=C:\hedef\klasör   (Sentinel Hub böyle kurar)
; --relaunch: kurulum bitince Compade'i aç (uygulama içi güncelleme kullanır)
Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!define APP "Compade"
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Compade"

Name "${APP} ${VERSION}"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "Software\${APP}" "InstallDir"
BrandingText "${APP} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APP} Setup"
VIAddVersionKey "LegalCopyright" "MIT"

!define MUI_ICON "${SRC}\_internal\compade\assets\compade.ico"
!define MUI_UNICON "${SRC}\_internal\compade\assets\compade.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP}.exe"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Turkish"

Var Relaunch

Function .onInit
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "--relaunch" $R1
  ${IfNot} ${Errors}
    StrCpy $Relaunch "1"
    Sleep 2500            ; uygulama içi güncelleme: eski Compade'in kapanmasını bekle
  ${EndIf}
FunctionEnd

Section "Compade" SecMain
  ; çalışan kopya dosyaları kilitler
  nsExec::Exec 'taskkill /IM "${APP}.exe" /F'
  Sleep 400
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\_internal"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall ${APP}.exe"
  WriteRegStr HKCU "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "sekullar"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\${APP}.exe"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Uninstall ${APP}.exe"'
  WriteRegStr HKCU "${UNKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall ${APP}.exe" /S'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${APP}.exe"
  ; sessiz kurulumda (Sentinel Hub, güncelleme) masaüstü kısayolunu kurulumu yapan yönetir
  ${IfNot} ${Silent}
    CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${APP}.exe"
  ${EndIf}
SectionEnd

Function .onInstSuccess
  ${If} $Relaunch == "1"
    Exec '"$INSTDIR\${APP}.exe"'
  ${EndIf}
FunctionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /IM "${APP}.exe" /F'
  Sleep 400
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${APP}.exe"
  Delete "$INSTDIR\Uninstall ${APP}.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKCU "${UNKEY}"
  DeleteRegKey HKCU "Software\${APP}"
  ; kullanıcı verisi (~\.compade: hesaplar, sohbetler, kayıtlar) bilerek silinmez
SectionEnd
