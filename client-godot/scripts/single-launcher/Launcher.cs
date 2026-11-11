using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("AgentLuo")]
[assembly: AssemblyProduct("AgentLuo")]
[assembly: AssemblyVersion("__ASSEMBLY_VERSION__")]
[assembly: AssemblyFileVersion("__FILE_VERSION__")]
[assembly: AssemblyInformationalVersion("__PRODUCT_VERSION__")]

internal static class Program
{
    private const string Version = "__LAUNCHER_VERSION__";
    private const string Payload = "payload.zip";

    [STAThread]
    private static int Main(string[] args)
    {
        var root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "AgentLuo-Single",
            Version);
        var executable = Path.Combine(root, "agentluo.exe");
        var ready = Path.Combine(root, ".ready");
        var wait = Array.IndexOf(args, "--launcher-wait") >= 0;
        var forward = Array.FindAll(args, argument => argument != "--launcher-wait");

        try
        {
            if (!File.Exists(ready) || !File.Exists(executable))
            {
                Extract(root);
                File.WriteAllText(ready, DateTime.UtcNow.ToString("o"));
            }

            var start = new ProcessStartInfo(executable)
            {
                WorkingDirectory = root,
                UseShellExecute = true,
            };
            if (forward.Length > 0)
                start.Arguments = string.Join(" ", Array.ConvertAll(forward, Quote));

            using (var process = Process.Start(start))
            {
                if (!wait || process == null)
                    return 0;
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "AgentLuo 启动失败：\n" + error.Message,
                "AgentLuo",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }
    }

    private static void Extract(string root)
    {
        if (Directory.Exists(root))
            Directory.Delete(root, true);
        Directory.CreateDirectory(root);

        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(Payload))
        {
            if (stream == null)
                throw new InvalidOperationException("内置运行文件缺失。");
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
                archive.ExtractToDirectory(root);
        }
    }

    private static string Quote(string value)
    {
        if (string.IsNullOrEmpty(value))
            return "\"\"";
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
