import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

// Serve Monaco from the local bundle instead of a CDN.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

interface Props {
  initialCode: string;
  autocomplete: boolean;
  onChange: (code: string) => void;
}

export function CodeEditor({ initialCode, autocomplete, onChange }: Props) {
  return (
    <Editor
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
