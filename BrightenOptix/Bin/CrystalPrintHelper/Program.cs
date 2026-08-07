using System;
using System.Collections.Generic;
using System.Data;
using System.Drawing.Printing;
using System.Linq;
using System.Runtime.InteropServices;
using CrystalDecisions.CrystalReports.Engine;

// Standalone .NET Framework 3.5 console helper that opens a .rpt with Crystal Reports,
// binds an XML data source, and prints it.
//
// This runs as its own process (rather than being called in-process from Python via
// pythonnet) because some Crystal Reports driver components (e.g. crdb_adoplus.dll) are
// mixed-mode assemblies built against CLR v2.0. .NET does not support in-process
// side-by-side loading of mixed-mode v2.0 assemblies inside a host already running CLR
// v4 (which is what pythonnet uses under 64-bit Python). Compiling this as its own exe
// lets the whole process start under CLR v2.0 natively, avoiding that limitation.
class Program
{
    // Formula functions supplied by the IDAutomation Data Matrix UFL, which is not
    // installed on this machine. When --ignore-missing-ufl is passed, any formula field
    // that calls one of these gets its text swapped for an empty string in memory (the
    // saved .rpt on disk is never touched) so the barcode renders blank instead of
    // blocking the whole print job.
    static readonly string[] MissingUflFunctions = {
        "IDAutomationDataMatrixEncoderDMSet",
        "IDAutomationDataMatrixEncoderDMGet",
        "DataMatrixSetOptions",
        "DataMatrixGetPart",
    };

    [StructLayout(LayoutKind.Sequential)]
    struct DEVMODE
    {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int dmFields;
        public short dmOrientation;
        public short dmPaperSize;
        public short dmPaperLength;
        public short dmPaperWidth;
        public short dmScale;
        public short dmCopies;
        public short dmDefaultSource;
        public short dmPrintQuality;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel;
        public int dmPelsWidth;
        public int dmPelsHeight;
        public int dmDisplayFlags;
        public int dmDisplayFrequency;
        public int dmICMMethod;
        public int dmICMIntent;
        public int dmMediaType;
        public int dmDitherType;
        public int dmReserved1;
        public int dmReserved2;
        public int dmPanningWidth;
        public int dmPanningHeight;
    }

    const int DM_ORIENTATION = 0x1;
    const short DMORIENT_PORTRAIT = 1;
    const short DMORIENT_LANDSCAPE = 2;
    // 3/4 aren't part of the official Win32 DEVMODE spec (only 1/2 are documented) — some
    // label printer drivers accept them for a 180/270 rotated orientation, but support is
    // driver-dependent and not guaranteed.
    const short DMORIENT_ROTATED_180 = 3;
    const short DMORIENT_ROTATED_270 = 4;

    [DllImport("kernel32.dll")]
    static extern IntPtr GlobalLock(IntPtr hMem);

    [DllImport("kernel32.dll")]
    static extern bool GlobalUnlock(IntPtr hMem);

    static int Main(string[] args)
    {
        var options = ParseArgs(args);
        if (options == null)
        {
            Console.Error.WriteLine(
                "Usage: CrystalPrintHelper.exe <rptPath> <xmlPath> [--printer name] " +
                "[--rotation 0|90|180|270] [--offset-x hundredthsOfInch] [--offset-y hundredthsOfInch] " +
                "[--ignore-missing-ufl]");
            return 2;
        }

        ReportDocument report = null;
        try
        {
            report = new ReportDocument();
            report.Load(options.RptPath);

            DataSet ds = new DataSet();
            ds.ReadXml(options.XmlPath);
            report.SetDataSource(ds);

            if (options.IgnoreMissingUfl)
            {
                NeutralizeMissingUflFormulas(report);
            }

            string printerName = options.PrinterName ?? report.PrintOptions.PrinterName;

            if (options.Rotation != 0 || options.OffsetX != 0 || options.OffsetY != 0)
            {
                PrinterSettings printerSettings = new PrinterSettings();
                printerSettings.PrinterName = printerName;
                PageSettings pageSettings = printerSettings.DefaultPageSettings;

                pageSettings.Margins = new Margins(
                    Math.Max(0, options.OffsetX),
                    pageSettings.Margins.Right,
                    Math.Max(0, options.OffsetY),
                    pageSettings.Margins.Bottom);

                ApplyRotation(printerSettings, pageSettings, options.Rotation);

                report.PrintToPrinter(printerSettings, pageSettings, false);
            }
            else
            {
                if (!string.IsNullOrEmpty(options.PrinterName))
                {
                    report.PrintOptions.PrinterName = options.PrinterName;
                }

                report.PrintToPrinter(1, false, 0, 0);
            }

            Console.WriteLine("OK");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ERROR: " + ex.Message);
            return 1;
        }
        finally
        {
            if (report != null)
            {
                report.Close();
                report.Dispose();
            }
        }
    }

    static void NeutralizeMissingUflFormulas(ReportDocument report)
    {
        // Collect targets in a read-only pass first, then mutate in a separate pass —
        // mutating .Text while still enumerating FormulaFields risks interacting badly
        // with the live RAS-backed collection.
        var targets = new List<KeyValuePair<FormulaFieldDefinition, string>>();
        foreach (FormulaFieldDefinition formula in report.DataDefinition.FormulaFields)
        {
            string text = formula.Text;
            if (string.IsNullOrEmpty(text))
            {
                continue;
            }

            bool callsMissingUfl = MissingUflFunctions.Any(fn =>
                text.IndexOf(fn, StringComparison.OrdinalIgnoreCase) >= 0);

            if (!callsMissingUfl)
            {
                continue;
            }

            // This report mixes Crystal syntax ("//" comments, numberVar/stringVar
            // declarations) and Basic syntax ("Dim x As Type" declarations, "'" comments)
            // across different formula fields, and each needs a different empty-value
            // replacement: Basic syntax requires an explicit "Formula = value" statement,
            // Crystal syntax just wants a bare expression. Basic syntax formulas here also
            // contain instructional comments with a stray ":=" in them, so detect on the
            // "Dim " keyword instead of ":=" (which false-matches inside those comments).
            bool isBasicSyntax = text.IndexOf("Dim ", StringComparison.Ordinal) >= 0;
            string emptyFormula = isBasicSyntax ? "Formula = \"\"" : "\"\"";

            targets.Add(new KeyValuePair<FormulaFieldDefinition, string>(formula, emptyFormula));
        }

        foreach (var target in targets)
        {
            try
            {
                target.Key.Text = target.Value;
            }
            catch (Exception)
            {
                // Formula isn't actually placed on the report layout (never evaluated),
                // so a failed rewrite here is harmless — leave its original (unreachable)
                // text in place.
            }
        }
    }

    static void ApplyRotation(PrinterSettings printerSettings, PageSettings pageSettings, int rotationDegrees)
    {
        switch (rotationDegrees)
        {
            case 0:
                pageSettings.Landscape = false;
                return;
            case 90:
                pageSettings.Landscape = true;
                return;
            case 180:
                SetRawOrientation(printerSettings, pageSettings, DMORIENT_ROTATED_180);
                return;
            case 270:
                SetRawOrientation(printerSettings, pageSettings, DMORIENT_ROTATED_270);
                return;
            default:
                throw new ArgumentException("--rotation must be 0, 90, 180, or 270");
        }
    }

    // 180/270 aren't standard Win32 orientations (only Portrait=1/Landscape=2 are part of
    // the documented DEVMODE spec) — this writes the raw dmOrientation field directly and
    // hopes the printer driver honors it. Whether it actually works depends entirely on
    // the driver; verify against a physical printout.
    static void SetRawOrientation(PrinterSettings printerSettings, PageSettings pageSettings, short orientation)
    {
        IntPtr hDevMode = printerSettings.GetHdevmode(pageSettings);
        IntPtr pDevMode = GlobalLock(hDevMode);
        try
        {
            DEVMODE dm = (DEVMODE)Marshal.PtrToStructure(pDevMode, typeof(DEVMODE));
            dm.dmFields |= DM_ORIENTATION;
            dm.dmOrientation = orientation;
            Marshal.StructureToPtr(dm, pDevMode, false);
        }
        finally
        {
            GlobalUnlock(hDevMode);
        }

        printerSettings.SetHdevmode(hDevMode);
        pageSettings.SetHdevmode(hDevMode);
    }

    class Options
    {
        public string RptPath;
        public string XmlPath;
        public string PrinterName;
        public int Rotation;
        public int OffsetX;
        public int OffsetY;
        public bool IgnoreMissingUfl;
    }

    static Options ParseArgs(string[] args)
    {
        var positional = new List<string>();
        var opts = new Options();

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--ignore-missing-ufl":
                    opts.IgnoreMissingUfl = true;
                    break;
                case "--printer":
                    opts.PrinterName = args[++i];
                    break;
                case "--rotation":
                    opts.Rotation = int.Parse(args[++i]);
                    break;
                case "--offset-x":
                    opts.OffsetX = int.Parse(args[++i]);
                    break;
                case "--offset-y":
                    opts.OffsetY = int.Parse(args[++i]);
                    break;
                default:
                    positional.Add(args[i]);
                    break;
            }
        }

        if (positional.Count < 2)
        {
            return null;
        }

        opts.RptPath = positional[0];
        opts.XmlPath = positional[1];
        return opts;
    }
}
