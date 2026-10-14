// Decompile every function into one C file. Args: <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompAll extends GhidraScript {
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        DecompInterface di = new DecompInterface();
        DecompileOptions opt = new DecompileOptions();
        di.setOptions(opt);
        di.toggleCCode(true);
        di.openProgram(currentProgram);
        PrintWriter pw = new PrintWriter(new BufferedWriter(new FileWriter(out)));
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int n = 0;
        while (it.hasNext() && !monitor.isCancelled()) {
            Function f = it.next();
            if (f.isThunk() || f.isExternal()) continue;
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            pw.println("// ==== " + f.getEntryPoint() + " " + f.getName());
            if (r != null && r.decompileCompleted()) pw.println(r.getDecompiledFunction().getC());
            else pw.println("// decompile failed");
            if (++n % 2000 == 0) { println("decompiled " + n); pw.flush(); }
        }
        pw.close();
        println("total " + n);
    }
}
