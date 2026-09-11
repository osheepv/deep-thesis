using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Collections.Generic;

// The workbench remains a local web application; this window owns its lifetime.
sealed class Launcher : Form
{
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly string storage = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Deep Thesis");
    readonly Label status = new Label { AutoSize = true, Text = "正在启动，请稍候…", Margin = new Padding(8) };
    readonly Button open = new Button { Text = "打开论文工作台", AutoSize = true, Enabled = false };
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 500 };
    Process service;
    string control, url;
    readonly object logLock = new object();
    StreamWriter log;

    [STAThread]
    static void Main()
    {
        bool first;
        using (var mutex = new Mutex(true, @"Local\DeepThesis.Desktop", out first))
        {
            if (!first) { MessageBox.Show("Deep Thesis 已在运行，请打开已有的启动窗口。", "Deep Thesis"); return; }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new Launcher());
        }
    }

    Launcher()
    {
        Text = "Deep Thesis · 测试版";
        Font = new Font("Microsoft YaHei UI", 10);
        ClientSize = new Size(540, 210);
        AutoScaleMode = AutoScaleMode.Dpi;
        StartPosition = FormStartPosition.CenterScreen;
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(16) };
        Controls.Add(layout);
        layout.Controls.Add(status);
        layout.Controls.Add(new Label { AutoSize = true, Text = "关闭浏览器后，仍可从这里重新打开。退出前请等待写作完成。", Margin = new Padding(8) });
        var buttons = new FlowLayoutPanel { AutoSize = true, WrapContents = true };
        buttons.Controls.Add(open);
        var data = new Button { Text = "论文数据", AutoSize = true };
        var logs = new Button { Text = "启动日志", AutoSize = true };
        var exit = new Button { Text = "退出程序", AutoSize = true };
        buttons.Controls.Add(data); buttons.Controls.Add(logs); buttons.Controls.Add(exit);
        layout.Controls.Add(buttons);
        open.Click += delegate { Open(url); };
        data.Click += delegate { Open(Path.Combine(storage, "data")); };
        logs.Click += delegate { if (control != null) Open(control); };
        exit.Click += delegate { Close(); };
        Shown += delegate { StartService(); };
        FormClosing += OnClosing;
        timer.Tick += delegate { CheckReady(); };
    }

    static string Quote(string value) { return "\"" + value + "\""; }
    void Open(string target)
    {
        try { Process.Start(new ProcessStartInfo(target) { UseShellExecute = true }); }
        catch (Exception error) { MessageBox.Show(this, error.Message, "无法打开"); }
    }

    void StartService()
    {
        try
        {
            control = Path.Combine(storage, "launcher", DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(control);
            Directory.CreateDirectory(Path.Combine(storage, "data"));
            log = new StreamWriter(Path.Combine(control, "startup.log"), false, System.Text.Encoding.UTF8) { AutoFlush = true };
            var info = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe")) {
                Arguments = Quote(Path.Combine(root, "app", "scripts", "run_preview.py")) +
                    " --data-dir " + Quote(Path.Combine(storage, "data")) +
                    " --api-port 18787 --ui-port 18788 --stop-file " + Quote(Path.Combine(control, "stop")) +
                    " --ready-file " + Quote(Path.Combine(control, "ready.json")) +
                    " --parent-pid " + Process.GetCurrentProcess().Id,
                WorkingDirectory = Path.Combine(root, "app"), UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8, StandardErrorEncoding = System.Text.Encoding.UTF8
            };
            // A desktop installation uses its own saved settings, not development overrides.
            var keys = new List<string>();
            foreach (string key in info.EnvironmentVariables.Keys)
                if (key.StartsWith("THESIS_") || key.StartsWith("DOCX_")) keys.Add(key);
            foreach (var key in keys) info.EnvironmentVariables.Remove(key);
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            service = new Process { StartInfo = info };
            service.OutputDataReceived += WriteLog;
            service.ErrorDataReceived += WriteLog;
            service.Start(); service.BeginOutputReadLine(); service.BeginErrorReadLine();
            timer.Start();
        }
        catch (Exception error) { status.Text = "启动失败，请查看日志。"; MessageBox.Show(this, error.Message, "Deep Thesis"); }
    }

    void WriteLog(object sender, DataReceivedEventArgs args)
    {
        if (args.Data != null) lock (logLock) { if (log != null) log.WriteLine(args.Data); }
    }

    void CheckReady()
    {
        if (service.HasExited) { timer.Stop(); open.Enabled = false; status.Text = "服务已停止，请查看启动日志后重新打开程序。"; return; }
        var ready = Path.Combine(control, "ready.json");
        if (url != null || !File.Exists(ready)) return;
        try
        {
            var result = new JavaScriptSerializer().Deserialize<Dictionary<string, string>>(File.ReadAllText(ready));
            url = result["url"];
            status.Text = "工作台已启动 · 论文保存在本机";
            open.Enabled = true;
            Open(url);
        }
        catch (IOException) { } // The supervisor may still be writing readiness.
        catch (ArgumentException) { }
    }

    void OnClosing(object sender, FormClosingEventArgs args)
    {
        if (service != null)
        {
            try
            {
                if (!service.HasExited)
                {
                    File.WriteAllText(Path.Combine(control, "stop"), "stop");
                    if (!service.WaitForExit(5000))
                    {
                        args.Cancel = true;
                        status.Text = "正在停止服务，请稍候再退出。";
                        return;
                    }
                }
            }
            catch (InvalidOperationException) { }
        }
        timer.Stop();
        lock (logLock) { if (log != null) { log.Dispose(); log = null; } }
    }
}
