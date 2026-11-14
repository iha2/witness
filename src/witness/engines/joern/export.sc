// Export METHOD nodes, CALL edges and REACHING_DEF edges as JSONL.
// Usage: joern --script export.sc --param cpgFile=<cpg> --param out=<file>
import java.io.PrintWriter

def esc(s: String): String =
  "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ") + "\""

@main def exec(cpgFile: String, out: String): Unit = {
  importCpg(cpgFile)
  val w = new PrintWriter(out)
  cpg.method.isExternal(false).foreach { m =>
    val s = m.lineNumber.getOrElse(0)
    val e = m.lineNumberEnd.getOrElse(s)
    w.println(s"""{"t":"node","id":${m.id},"kind":"METHOD","path":${esc(m.filename)},"qname":${esc(m.fullName)},"sig":${esc(m.signature)},"line":[$s,$e]}""")
  }
  cpg.call.foreach { c =>
    c.callee.foreach { t =>
      w.println(s"""{"t":"edge","src":${c.method.id},"dst":${t.id},"kind":"CALL"}""")
    }
  }
  cpg.call.foreach { c =>
    c.argument.reachingDefIn.foreach { d =>
      w.println(s"""{"t":"edge","src":${d.id},"dst":${c.id},"kind":"REACHING_DEF"}""")
    }
  }
  w.close()
}
