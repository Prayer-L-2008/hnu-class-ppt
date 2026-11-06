// 原生单文件安装程序：exe 尾部追加 app.zip，安装时释放并用 PowerShell 解压到目标目录
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <commctrl.h>
#ifndef PBS_MARQUEE
#define PBS_MARQUEE 0x08
#endif
#ifndef PBM_SETMARQUEE
#define PBM_SETMARQUEE (WM_USER + 10)
#endif
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


// ---------------- 安装进度窗口 ----------------
static HWND g_hwnd = nullptr, g_hbar = nullptr, g_htext = nullptr;
static bool g_ok = false;
static std::wstring g_zip, g_target, g_exe;

static void PostStatus(const wchar_t* s) {
    PostMessageW(g_hwnd, WM_APP + 1, 0, (LPARAM)new std::wstring(s));
}

static LRESULT CALLBACK ProgProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_APP + 1: {
        auto* s = reinterpret_cast<std::wstring*>(l);
        if (s) { SetWindowTextW(g_htext, s->c_str()); delete s; }
        return 0;
    }
    case WM_TIMER: {
        LRESULT pos = SendMessageW(g_hbar, PBM_GETPOS, 0, 0);
        if (pos < 88) SendMessageW(g_hbar, PBM_SETPOS, (WPARAM)(pos + 1), 0);
        return 0;
    }
    case WM_APP + 2:
        SendMessageW(g_hbar, PBM_SETPOS, 100, 0);
        KillTimer(h, 1);
        DestroyWindow(h);
        return 0;
    case WM_APP + 3:
        MessageBoxW(h, L"解压失败：目标目录可能不可写，或安装包已损坏。", L"安装失败", MB_ICONERROR);
        DestroyWindow(h);
        return 0;
    case WM_CLOSE:
        return 0; // 安装过程中不允许关闭
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

static DWORD WINAPI InstallWorker(LPVOID) {
    PostStatus(L"正在解压程序文件（约 10–30 秒，请稍候）…");
    if (!ExtractPayload(g_zip, g_target)) {
        PostMessageW(g_hwnd, WM_APP + 3, 0, 0);
        return 0;
    }
    DeleteFileW(g_zip.c_str());
    PostStatus(L"正在创建桌面和开始菜单快捷方式…");
    MakeShortcuts(g_exe);
    PostStatus(L"安装完成");
    Sleep(400);
    g_ok = true;
    PostMessageW(g_hwnd, WM_APP + 2, 0, 0);
    return 0;
}

static bool RunWithProgress(const std::wstring& zip, const std::wstring& target, const std::wstring& exe) {
    g_zip = zip; g_target = target; g_exe = exe; g_ok = false;

    INITCOMMONCONTROLSEX icc{ sizeof(icc), ICC_PROGRESS_CLASS };
    InitCommonControlsEx(&icc);

    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = ProgProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.hCursor = LoadCursorW(nullptr, (LPCWSTR)IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = L"HNUClassInstallWnd";
    wc.hIcon = LoadIconW(wc.hInstance, MAKEINTRESOURCEW(101));
    wc.hIconSm = wc.hIcon;
    RegisterClassExW(&wc);

    HDC screen = GetDC(nullptr);
    int dpi = GetDeviceCaps(screen, LOGPIXELSY);
    ReleaseDC(nullptr, screen);
    if (dpi <= 0) dpi = 96;
    const double sc = dpi / 96.0;
    auto S = [sc](int v) { return (int)(v * sc + 0.5); };

    const int W = S(480), H = S(190);
    int x = (GetSystemMetrics(SM_CXSCREEN) - W) / 2;
    int y = (GetSystemMetrics(SM_CYSCREEN) - H) / 2;
    g_hwnd = CreateWindowExW(WS_EX_TOPMOST, L"HNUClassInstallWnd", L"湖大课件生成器 安装程序",
                             WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU,
                             x, y, W, H, nullptr, nullptr, wc.hInstance, nullptr);
    if (!g_hwnd) return false;

    HFONT font = CreateFontW(-MulDiv(9, dpi, 72), 0, 0, 0, FW_NORMAL, 0, 0, 0,
                             DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                             CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Microsoft YaHei UI");
    if (!font) font = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HWND title = CreateWindowExW(0, L"STATIC", L"正在安装「湖大课件生成器」", WS_CHILD | WS_VISIBLE,
                                 S(20), S(18), W - S(40), S(24), g_hwnd, nullptr, wc.hInstance, nullptr);
    SendMessageW(title, WM_SETFONT, (WPARAM)font, TRUE);

    g_htext = CreateWindowExW(0, L"STATIC", L"正在准备安装…", WS_CHILD | WS_VISIBLE,
                              S(20), S(52), W - S(40), S(42), g_hwnd, nullptr, wc.hInstance, nullptr);
    SendMessageW(g_htext, WM_SETFONT, (WPARAM)font, TRUE);

    g_hbar = CreateWindowExW(0, PROGRESS_CLASSW, nullptr, WS_CHILD | WS_VISIBLE,
                             S(20), S(104), W - S(40), S(20), g_hwnd, nullptr, wc.hInstance, nullptr);
    SendMessageW(g_hbar, PBM_SETRANGE, 0, MAKELPARAM(0, 100));
    SendMessageW(g_hbar, PBM_SETPOS, 3, 0);
    SetTimer(g_hwnd, 1, 120, nullptr);

    HWND hint = CreateWindowExW(0, L"STATIC", L"安装完成后会提示，请勿关闭此窗口。", WS_CHILD | WS_VISIBLE,
                                S(20), S(132), W - S(40), S(20), g_hwnd, nullptr, wc.hInstance, nullptr);
    SendMessageW(hint, WM_SETFONT, (WPARAM)font, TRUE);

    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);

    CreateThread(nullptr, 0, InstallWorker, nullptr, 0, nullptr);

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return g_ok;
}

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);

    std::wstring target;
    bool silent = false, launch = true;
    for (int i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--silent") == 0 && i + 1 < argc) { target = argv[++i]; silent = true; }
        else if (wcscmp(argv[i], L"--dir") == 0 && i + 1 < argc) { target = argv[++i]; }
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
    std::wstring exe = target + L"\\HNUClassPPT.exe";
    bool ok = false;
    if (silent) {
        ok = ExtractPayload(zip, target);
        if (ok) { DeleteFileW(zip.c_str()); MakeShortcuts(exe); }
    } else {
        ok = RunWithProgress(zip, target, exe);
    }
    if (!ok) {
        if (silent)
            MessageBoxW(nullptr, (L"解压失败，目标目录是否可写？\n" + target).c_str(),
                        L"安装失败", MB_ICONERROR);
        DeleteFileW(zip.c_str());
        LocalFree(argv);
        return 2;
    }

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
