// 原生单文件安装程序：exe 尾部追加 app.zip，安装时释放并用 PowerShell 解压到目标目录
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <string>
#include <cstdio>

static std::wstring ExePath() {
    wchar_t buf[MAX_PATH * 4];
    GetModuleFileNameW(nullptr, buf, MAX_PATH * 4);
    return buf;
}

static bool RunWait(const std::wstring& cmdline) {
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    std::wstring c = cmdline;
    if (!CreateProcessW(nullptr, (LPWSTR)c.c_str(), nullptr, nullptr, FALSE,
                        CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi))
        return false;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return code == 0;
}

static std::wstring PSCmd(const std::wstring& body) {
    return L"powershell -NoProfile -ExecutionPolicy Bypass -Command \"" + body + L"\"";
}

static bool ExtractPayload(const std::wstring& zipPath, const std::wstring& target) {
    std::wstring body =
        L"Expand-Archive -LiteralPath '" + zipPath + L"' -DestinationPath '" + target + L"' -Force";
    return RunWait(PSCmd(body));
}

static void MakeShortcuts(const std::wstring& exe) {
    wchar_t desk[MAX_PATH], prog[MAX_PATH];
    SHGetSpecialFolderPathW(nullptr, desk, CSIDL_DESKTOPDIRECTORY, FALSE);
    SHGetSpecialFolderPathW(nullptr, prog, CSIDL_PROGRAMS, FALSE);
    std::wstring d = std::wstring(desk) + L"\\湖大课件生成器.lnk";
    std::wstring p = std::wstring(prog) + L"\\湖大课件生成器.lnk";
    std::wstring body =
        L"$ws=New-Object -ComObject WScript.Shell;"
        L"foreach($l in @('" + d + L"','" + p + L"')){"
        L"$s=$ws.CreateShortcut($l);$s.TargetPath='" + exe + L"';"
        L"$s.WorkingDirectory='" + exe.substr(0, exe.find_last_of(L'\\')) + L"';"
        L"$s.IconLocation='" + exe + L",0';$s.Save()}";
    RunWait(PSCmd(body));
}

static bool CopyPayloadTo(const std::wstring& self, const std::wstring& zipOut) {
    FILE* f = _wfopen(self.c_str(), L"rb");
    if (!f) return false;
    _fseeki64(f, 0, SEEK_END);
    __int64 size = _ftelli64(f);
    if (size < 16) { fclose(f); return false; }
    _fseeki64(f, size - 8, SEEK_SET);
    unsigned __int64 off = 0;
    if (fread(&off, 8, 1, f) != 1 || off < 1024 || off >= (unsigned __int64)size) { fclose(f); return false; }
    _fseeki64(f, (__int64)off, SEEK_SET);
    FILE* o = _wfopen(zipOut.c_str(), L"wb");
    if (!o) { fclose(f); return false; }
    char buf[1 << 16];
    unsigned long long left = (unsigned long long)size - 8 - off;
    while (left > 0) {
        size_t n = (size_t)(left > sizeof(buf) ? sizeof(buf) : left);
        if (fread(buf, 1, n, f) != n) break;
        fwrite(buf, 1, n, o);
        left -= n;
    }
    fclose(o);
    fclose(f);
    return left == 0;
}

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);

    std::wstring target;
    bool silent = false, launch = true;
    for (int i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--silent") == 0 && i + 1 < argc) { target = argv[++i]; silent = true; }
        else if (wcscmp(argv[i], L"--no-launch") == 0) launch = false;
    }

    if (target.empty()) {
        wchar_t buf[MAX_PATH];
        SHGetSpecialFolderPathW(nullptr, buf, CSIDL_LOCAL_APPDATA, FALSE);
        target = std::wstring(buf) + L"\\Programs\\HNUClassPPT";
        std::wstring msg = L"将把「湖大课件生成器」安装到：\n\n" + target +
                           L"\n\n选择「是」开始安装；选择「否」可更换安装位置。";
        int r = MessageBoxW(nullptr, msg.c_str(), L"安装 湖大课件生成器",
                            MB_YESNOCANCEL | MB_ICONQUESTION);
        if (r == IDCANCEL) { LocalFree(argv); return 0; }
        if (r == IDNO) {
            BROWSEINFOW bi{};
            bi.lpszTitle = L"选择安装位置（会在此文件夹下创建 HNUClassPPT）";
            bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
            LPITEMIDLIST idl = SHBrowseForFolderW(&bi);
            wchar_t sel[MAX_PATH];
            if (idl && SHGetPathFromIDListW(idl, sel)) target = std::wstring(sel) + L"\\HNUClassPPT";
            else { LocalFree(argv); return 0; }
        }
    }

    std::wstring self = ExePath();
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    std::wstring zip = std::wstring(tmp) + L"hnuclass_payload.zip";

    if (!CopyPayloadTo(self, zip)) {
        MessageBoxW(nullptr, L"安装包损坏：找不到内嵌的程序数据。", L"安装失败", MB_ICONERROR);
        LocalFree(argv);
        return 1;
    }

    CreateDirectoryW(target.c_str(), nullptr);
    if (!ExtractPayload(zip, target)) {
        MessageBoxW(nullptr, (L"解压失败，目标目录是否可写？\n" + target).c_str(),
                    L"安装失败", MB_ICONERROR);
        DeleteFileW(zip.c_str());
        LocalFree(argv);
        return 2;
    }
    DeleteFileW(zip.c_str());

    std::wstring exe = target + L"\\HNUClassPPT.exe";
    MakeShortcuts(exe);

    if (launch) {
        std::wstring wd = target;
        STARTUPINFOW si{};
        si.cb = sizeof(si);
        PROCESS_INFORMATION pi{};
        std::wstring cmd = L"\"" + exe + L"\"";
        CreateProcessW(nullptr, (LPWSTR)cmd.c_str(), nullptr, nullptr, FALSE,
                       0, nullptr, wd.c_str(), &si, &pi);
        if (pi.hProcess) CloseHandle(pi.hProcess);
        if (pi.hThread) CloseHandle(pi.hThread);
    }

    if (!silent) {
        MessageBoxW(nullptr, (L"安装完成！\n\n桌面和开始菜单已创建「湖大课件生成器」快捷方式。\n"
                              L"安装目录内提供 uninstall.exe 用于卸载。\n\n" + target).c_str(),
                    L"安装完成", MB_ICONINFORMATION);
    }
    LocalFree(argv);
    return 0;
}
