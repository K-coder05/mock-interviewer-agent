import { useRef } from "react";
import Editor, { loader } from "@monaco-editor/react";
import type { OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

// Serve Monaco from the local bundle instead of a CDN.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

interface Props {
  initialCode: string;
  autocomplete: boolean;
  onChange: (code: string) => void;
  /** Called with the live buffer on Cmd/Ctrl+Enter. */
  onRun: (code: string) => void;
}

export function CodeEditor({ initialCode, autocomplete, onChange, onRun }: Props) {
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;
  const handleMount: OnMount = (editor) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () =>
      onRunRef.current(editor.getValue()),
    );
  };
  return (
    <Editor
      onMount={handleMount}
      defaultLanguage="python"
      defaultValue={initialCode}
      theme="vs-dark"
      onChange={(value) => onChange(value ?? "")}
      options={{
        tabSize: 4,
        insertSpaces: true,
        detectIndentation: false,
        minimap: { enabled: false },
        fontSize: 14,
        automaticLayout: true,
        scrollBeyondLastLine: false,
        // Interview realism: no autocomplete / IntelliSense unless chosen at setup.
        quickSuggestions: autocomplete,
        suggestOnTriggerCharacters: autocomplete,
        wordBasedSuggestions: autocomplete ? "currentDocument" : "off",
        parameterHints: { enabled: autocomplete },
        acceptSuggestionOnEnter: autocomplete ? "on" : "off",
        tabCompletion: autocomplete ? "on" : "off",
        snippetSuggestions: autocomplete ? "inline" : "none",
        inlineSuggest: { enabled: autocomplete },
        suggest: { showWords: autocomplete, showSnippets: autocomplete },
      }}
    />
  );
}
