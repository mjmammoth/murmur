import { createMemo, type JSX } from "solid-js";
import { useKeyHandler } from "@opentui/solid";
import { SyntaxStyle, RGBA, type SimpleHighlight, type KeyEvent } from "@opentui/core";
import { useTheme } from "../context/theme";
import { useBackend } from "../context/backend";
import { useDialog } from "../context/dialog";

function createTomlSyntaxStyle(): SyntaxStyle {
  return SyntaxStyle.fromStyles({
    comment: { fg: RGBA.fromHex("#6B7280"), dim: true },
    section: { fg: RGBA.fromHex("#7C3AED") },
    key: { fg: RGBA.fromHex("#F9FAFB") },
    string: { fg: RGBA.fromHex("#10B981") },
    number: { fg: RGBA.fromHex("#22D3EE") },
    boolean: { fg: RGBA.fromHex("#F59E0B") },
    operator: { fg: RGBA.fromHex("#6B7280"), dim: true },
  });
}

function highlightToml(
  highlights: SimpleHighlight[],
  context: { content: string },
): SimpleHighlight[] {
  const result: SimpleHighlight[] = [];
  const lines = context.content.split("\n");
  let offset = 0;

  for (const line of lines) {
    const trimmed = line.trimStart();

    if (trimmed.startsWith("#")) {
      // Comment line
      const commentStart = offset + line.indexOf("#");
      result.push([commentStart, offset + line.length, "comment"]);
    } else if (trimmed.startsWith("[")) {
      // Section header [section] or [[array]]
      result.push([offset, offset + line.length, "section"]);
    } else if (trimmed.includes("=")) {
      const eqIdx = line.indexOf("=");
      const absEq = offset + eqIdx;

      // Key (before =)
      const keyText = line.substring(0, eqIdx).trimEnd();
      if (keyText.length > 0) {
        result.push([offset, offset + keyText.length, "key"]);
      }

      // Operator (=)
      result.push([absEq, absEq + 1, "operator"]);

      // Value (after =)
      const valueStr = line.substring(eqIdx + 1).trimStart();
      const valueStart = offset + line.indexOf(valueStr, eqIdx + 1);
      const valueEnd = offset + line.length;

      // Check for inline comment
      let valText = valueStr;
      let inlineCommentStart = -1;

      // Simple inline comment detection (not inside quotes)
      if (!valueStr.startsWith('"') && !valueStr.startsWith("'")) {
        const hashIdx = valueStr.indexOf(" #");
        if (hashIdx >= 0) {
          inlineCommentStart = valueStart + hashIdx + 1;
          valText = valueStr.substring(0, hashIdx).trimEnd();
        }
      }

      const valEnd = inlineCommentStart >= 0 ? valueStart + valText.length : valueEnd;

      if (valText.startsWith('"') || valText.startsWith("'")) {
        result.push([valueStart, valEnd, "string"]);
      } else if (valText === "true" || valText === "false") {
        result.push([valueStart, valEnd, "boolean"]);
      } else if (/^-?\d+(\.\d+)?$/.test(valText)) {
        result.push([valueStart, valEnd, "number"]);
      } else {
        result.push([valueStart, valEnd, "string"]);
      }

      if (inlineCommentStart >= 0) {
        result.push([inlineCommentStart, valueEnd, "comment"]);
      }
    }

    offset += line.length + 1; // +1 for newline
  }

  return result;
}

export function Settings(): JSX.Element {
  const { colors } = useTheme();
  const backend = useBackend();
  const dialog = useDialog();

  const syntaxStyle = createTomlSyntaxStyle();

  useKeyHandler((key: KeyEvent) => {
    if (dialog.currentDialog()?.type !== "settings") return;
    if (key.name === "escape") {
      dialog.closeDialog();
    }
  });

  const content = createMemo(() => backend.configFileContent() || "# No config file found");
  const filePath = createMemo(() => backend.configFilePath() || "~/.config/whisper-local/config.toml");

  return (
    <box
      flexDirection="column"
      width={70}
      height={24}
      backgroundColor={colors().backgroundPanel}
      borderStyle="rounded"
      borderColor={colors().border}
      padding={1}
    >
      {/* Header */}
      <box paddingX={1} paddingBottom={1} flexDirection="column">
        <text>
          <span fg={colors().primary}>{"◆"}</span>
          <span fg={colors().text}> Settings</span>
        </text>
        <text>
          <span fg={colors().textDim}>{filePath()}</span>
        </text>
      </box>

      {/* Divider */}
      <box paddingX={1}>
        <text>
          <span fg={colors().borderSubtle}>
            {"─".repeat(66)}
          </span>
        </text>
      </box>

      {/* Code display */}
      <scrollbox flexGrow={1} paddingY={1} paddingX={1}>
        <code
          content={content()}
          syntaxStyle={syntaxStyle}
          onHighlight={highlightToml}
        />
      </scrollbox>

      {/* Footer */}
      <box paddingX={1} paddingTop={1}>
        <text>
          <span fg={colors().textDim}>[esc]</span>
          <span fg={colors().textMuted}> close</span>
        </text>
      </box>
    </box>
  );
}
