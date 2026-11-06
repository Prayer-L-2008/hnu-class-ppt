// 原生卸载程序（无 Python 运行时）：确认 -> 删快捷方式 -> 复制自身到 TEMP -> 递归删除安装目录
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <string>

static std::wstring ExePath() {
    wchar_t buf[MAX_PATH * 4];
    GetModuleFileNameW(nullptr, buf, MAX_PATH * 4);
    return buf;
}

static void DelTree(const std::wstring& p) {
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((p + L"\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
            std::wstring c = p + L"\\" + fd.cFileName;
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) DelTree(c);
            else {
                SetFileAttributesW(c.c_str(), FILE_ATTRIBUTE_NORMAL);
                DeleteFileW(c.c_str());
            }
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    RemoveDirectoryW(p.c_str());
}

static void KillShortcuts() {
    wchar_t buf[MAX_PATH];
    std::wstring name = L"\\湖大课件生成器.lnk";
    if (SHGetSpecialFolderPathW(nullptr, buf, CSIDL_DESKTOPDIRECTORY, FALSE))
        DeleteFileW((std::wstring(buf) + name).c_str());
    if (SHGetSpecialFolderPathW(nullptr, buf, CSIDL_PROGRAMS, FALSE))
        DeleteFileW((std::wstring(buf) + name).c_str());
}

static void SelfDelete(const std::wstring& self) {
    MoveFileExW(self.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
}

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);

    if (argc >= 3 && wcscmp(argv[1], L"--purge") == 0) {
        std::wstring dir = argv[2];
        DelTree(dir);
        SelfDelete(ExePath());
        LocalFree(argv);
        return 0;
    }

    std::wstring self = ExePath();
    std::wstring dir = self;
    size_t pos = dir.find_last_of(L"\\/");
    if (pos != std::wstring::npos) dir = dir.substr(0, pos);

    std::wstring msg = L"确定要卸载「湖大课件生成器」吗？\n\n安装目录：\n" + dir +
                       L"\n\n登录状态和 API Key 会保留在 %LOCALAPPDATA%\\hnuclass。";
    bool autoYes = (argc >= 2 && wcscmp(argv[1], L"--auto") == 0);
    if (!autoYes && MessageBoxW(nullptr, msg.c_str(), L"卸载湖大课件生成器",
                    MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) {
        LocalFree(argv);
        return 0;
    }

    KillShortcuts();

    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    std::wstring copy = std::wstring(tmp) + L"hnuclass_uninstall_tmp.exe";
    CopyFileW(self.c_str(), copy.c_str(), FALSE);

    std::wstring cmd = L"\"" + copy + L"\" --purge \"" + dir + L"\"";
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    CreateProcessW(nullptr, (LPWSTR)cmd.c_str(), nullptr, nullptr, FALSE,
                   CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi);
    if (pi.hProcess) CloseHandle(pi.hProcess);
    if (pi.hThread) CloseHandle(pi.hThread);

    LocalFree(argv);
    return 0;
}
