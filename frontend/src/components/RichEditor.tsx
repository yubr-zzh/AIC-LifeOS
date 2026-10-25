import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { useEffect, useRef } from "react";

interface RichEditorProps {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  minHeight?: number;
  ariaLabel?: string;
}

export function RichEditor({ value, onChange, placeholder, minHeight = 200, ariaLabel }: RichEditorProps) {
  const lastEmitted = useRef<string>(value);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Placeholder.configure({ placeholder: placeholder || "开始写…" }),
    ],
    content: value,
    editorProps: {
      attributes: {
        class: "rich-editor",
        "aria-label": ariaLabel ?? "文本编辑",
        role: "textbox",
        "aria-multiline": "true",
        style: `min-height:${minHeight}px`,
      },
    },
    onUpdate: ({ editor: ed }) => {
      const html = ed.getHTML();
      if (html !== lastEmitted.current) {
        lastEmitted.current = html;
        onChange(html);
      }
    },
  });

  useEffect(() => {
    if (!editor) return;
    if (value !== lastEmitted.current && value !== editor.getHTML()) {
      lastEmitted.current = value;
      editor.commands.setContent(value, { emitUpdate: false });
    }
  }, [value, editor]);

  useEffect(() => () => editor?.destroy(), [editor]);

  return (
    <div className="rich-editor-wrap">
      <EditorContent editor={editor} />
      <EditorToolbar editor={editor} />
    </div>
  );
}

function EditorToolbar({ editor }: { editor: ReturnType<typeof useEditor> }) {
  if (!editor) return null;
  return (
    <div className="rich-editor-toolbar" role="toolbar" aria-label="文本格式">
      <button
        type="button"
        className={`rtb-btn ${editor.isActive("bold") ? "is-active" : ""}`}
        onClick={() => editor.chain().focus().toggleBold().run()}
        aria-label="加粗"
        title="加粗 (Ctrl+B)"
      >
        <strong>B</strong>
      </button>
      <button
        type="button"
        className={`rtb-btn ${editor.isActive("italic") ? "is-active" : ""}`}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        aria-label="斜体"
        title="斜体 (Ctrl+I)"
      >
        <em>I</em>
      </button>
      <span className="rtb-sep" />
      <button
        type="button"
        className={`rtb-btn ${editor.isActive("heading", { level: 2 }) ? "is-active" : ""}`}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        aria-label="二级标题"
        title="二级标题"
      >
        H2
      </button>
      <button
        type="button"
        className={`rtb-btn ${editor.isActive("bulletList") ? "is-active" : ""}`}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        aria-label="无序列表"
        title="无序列表"
      >
        •
      </button>
      <button
        type="button"
        className={`rtb-btn ${editor.isActive("orderedList") ? "is-active" : ""}`}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        aria-label="有序列表"
        title="有序列表"
      >
        1.
      </button>
      <button
        type="button"
        className={`rtb-btn ${editor.isActive("blockquote") ? "is-active" : ""}`}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        aria-label="引用"
        title="引用"
      >
        ❝
      </button>
      <span className="rtb-sep" />
      <button
        type="button"
        className="rtb-btn"
        onClick={() => editor.chain().focus().undo().run()}
        disabled={!editor.can().undo()}
        aria-label="撤销"
        title="撤销"
      >
        ↶
      </button>
      <button
        type="button"
        className="rtb-btn"
        onClick={() => editor.chain().focus().redo().run()}
        disabled={!editor.can().redo()}
        aria-label="重做"
        title="重做"
      >
        ↷
      </button>
    </div>
  );
}
