#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dart Dump Builder (GUI) — perfiles + EXTRAS con exclusiones
-----------------------------------------------------------
• Escanea un proyecto Flutter.
• Selección visual (tipo checkbox) de qué archivos incluir:
    - Todo lo de /lib con filtro por extensiones (por defecto .dart).
    - EXTRAS: añade archivos, patrones o carpetas completas con
      un selector propio que permite excluir subcarpetas/archivos
      ANTES de agregarlos.
• Guarda y carga perfiles de trabajo (varias configuraciones).
  Los perfiles se guardan en: ~/.dart_dump_gui_profiles.json
• Genera un TXT con el formato solicitado:
  encabezados para carpetas (Dentro de /X: …) y líneas tipo
  "ruta/archivo.dart>" seguidas del código.

Probado con Python 3.13.7.

Uso:
  python dart_dump_gui.py
"""

from __future__ import annotations

import json
import os
import sys
import glob as _glob
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, TextIO, Tuple

# --- Tkinter (estándar) ---
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


# =================== CONFIGURACIÓN INICIAL ===================

DEFAULT_PROJECT_ROOT: str = (
    "C:/Users/marqu/Programacion/App100MujeresTrabajando/flutter_application_emprendedoras"
)
DEFAULT_EXTENSIONS: str = "dart"            # extensiones (coma) para lib/
DEFAULT_EXCLUDES: str = ".git,build,.dart_tool,.idea,.vscode"

PROFILE_STORE: str = os.path.expanduser("~/.dart_dump_gui_profiles.json")

# ============================================================


def sorted_casefold(items: Iterable[str]) -> List[str]:
    return sorted(items, key=lambda s: s.casefold())


def dir_header(depth: int, dirname: str) -> str:
    if depth == 1:
        return f"Dentro de /{dirname}:\n"
    elif depth == 2:
        return f"En /{dirname}:\n"
    else:
        indent = "    " * (depth - 1)
        return f"{indent}/{dirname}:\n"


def write_file_block(out_fh: TextIO, file_abs_path: str, root_for_rel: str, filename_only: bool) -> int:
    """Imprime '<ruta_relativa_o_nombre>' + contenido + doble salto. Devuelve bytes aprox. escritos."""
    rel = os.path.relpath(file_abs_path, root_for_rel).replace(os.sep, "/")
    header = os.path.basename(rel) if filename_only else rel
    out_fh.write(f"{header}>\n")
    written = 0
    try:
        with open(file_abs_path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
            out_fh.write(content)
            written = len(content)
    except Exception as e:
        msg = f"[ERROR al leer el archivo: {e}]\n"
        out_fh.write(msg)
        written = len(msg)
    out_fh.write("\n\n")
    return written


CHECK_OFF = "☐"
CHECK_ON = "☑"
CHECK_PARTIAL = "◩"  # para carpetas parcialmente seleccionadas


@dataclass
class NodeMeta:
    kind: str              # "root-extras" | "root-lib" | "dir" | "file" | "extra-group"
    path: str              # ruta absoluta si aplica (archivo/dir)
    root_for_rel: str      # base para rutas relativas en encabezados
    group: str             # "extras" | "lib" | "extras-group"
    label: str             # texto base sin prefijo de checkbox
    selectable: bool = True


# ---------- Perfiles ----------

def _load_profile_store() -> Dict[str, Any]:
    if not os.path.isfile(PROFILE_STORE):
        return {}
    try:
        with open(PROFILE_STORE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_profile_store(store: Dict[str, Any]) -> None:
    try:
        with open(PROFILE_STORE, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        messagebox.showwarning("Aviso", f"No se pudo guardar el archivo de perfiles:\n{e}")


# ---------- Diálogo de selección desde carpeta (con exclusiones) ----------

class SelectFromFolderDialog(tk.Toplevel):
    """Muestra una vista en árbol de una carpeta y permite pre-seleccionar qué incluir."""
    def __init__(self, master: tk.Misc, base_dir: str, ext_filter: Optional[Set[str]] = None, title: str = "Seleccionar desde carpeta") -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("800x520")
        self.resizable(True, True)

        # Nota: tiposhed es estricto con wm_transient; ignoramos el tipo para evitar warning.
        try:
            self.transient(master)  # type: ignore[arg-type]
        except Exception:
            pass
        self.grab_set()

        self.base_dir = os.path.abspath(base_dir)
        self.ext_filter = {e.lower().lstrip(".") for e in (ext_filter or set())} or None

        self.item_state: Dict[str, int] = {}   # 0/1/2
        self.item_meta: Dict[str, NodeMeta] = {}
        self.result_paths: Optional[List[str]] = None

        # Top
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text=f"Carpeta base: {self.base_dir}").pack(anchor="w")

        # Centro
        mid = ttk.Frame(self, padding=(6,0,6,6))
        mid.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(mid, columns=("dummy",), show="tree")
        yscroll = ttk.Scrollbar(mid, orient="vertical")

        # Scroll wrappers sin usar .yview() directamente (evita warnings de tipo)
        self._y_first: float = 0.0
        self._y_last: float = 1.0

        def _tree_yview(*args: Any) -> None:
            if not args:
                return
            op = str(args[0])
            if op == "moveto" and len(args) >= 2:
                try:
                    self.tree.yview_moveto(float(args[1]))
                except Exception:
                    pass
                return
            if op == "scroll" and len(args) >= 3:
                try:
                    count = int(args[1])
                except Exception:
                    count = 0
                token = str(args[2])
                first = self._y_first
                last = self._y_last
                page_step = max(0.0, min(1.0, last - first))
                unit_step = 0.05
                step = page_step if token == "pages" else unit_step
                new_first = max(0.0, min(1.0, first + count * step))
                self.tree.yview_moveto(new_first)

        def _yscroll_set(first: float, last: float) -> None:
            self._y_first, self._y_last = first, last
            yscroll.set(first, last)

        self.tree.configure(yscrollcommand=_yscroll_set)
        yscroll.config(command=_tree_yview)

        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_space)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Return>", self._on_space)

        # Lateral
        right = ttk.Frame(mid)
        right.pack(side="right", fill="y", padx=8)
        ttk.Button(right, text="Seleccionar todo", command=lambda: self._toggle_all(True)).pack(fill="x", pady=2)
        ttk.Button(right, text="Deseleccionar todo", command=lambda: self._toggle_all(False)).pack(fill="x", pady=2)
        ttk.Button(right, text="Expandir", command=lambda: self._expand_collapse(True)).pack(fill="x", pady=8)
        ttk.Button(right, text="Colapsar", command=lambda: self._expand_collapse(False)).pack(fill="x", pady=1)

        # Bottom
        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Cancelar", command=self._cancel).pack(side="right", padx=4)
        ttk.Button(bottom, text="Agregar selección", command=self._accept).pack(side="right", padx=4)

        # Construir árbol anidado correctamente
        base_label = os.path.basename(self.base_dir.strip("\\/")) or self.base_dir
        self.root_item = self._add_dir_node("", base_label, self.base_dir, self.base_dir, "dialog")
        path_to_node: Dict[str, str] = {self.base_dir: self.root_item}

        for root, dirs, files in os.walk(self.base_dir, topdown=True):
            dirs[:] = sorted_casefold(dirs)
            files = sorted_casefold(files)

            parent_node = path_to_node.get(root, self.root_item)

            # Subcarpetas
            for d in dirs:
                dpath = os.path.join(root, d)
                node = self._add_dir_node(parent_node, d, dpath, self.base_dir, "dialog")
                path_to_node[dpath] = node

            # Archivos
            for f in files:
                if self.ext_filter is not None:
                    ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                    if ext not in self.ext_filter:
                        continue
                fpath = os.path.join(root, f)
                self._add_file_node(parent_node, f, fpath, self.base_dir, "dialog", default_on=True)

        self.tree.item(self.root_item, open=True)

    # --- utilidades internas del diálogo ---
    def _set_item_text(self, item: str, base: str, state: int) -> None:
        prefix = CHECK_OFF if state == 0 else CHECK_ON if state == 1 else CHECK_PARTIAL
        self.tree.item(item, text=f"{prefix} {base}")

    def _add_dir_node(self, parent: str, label: str, path: str, root_for_rel: str, group: str) -> str:
        node = self.tree.insert(parent, "end", text=f"{CHECK_ON} {label}", open=False)
        self.item_meta[node] = NodeMeta("dir", path, root_for_rel, group, label, selectable=True)
        self.item_state[node] = 1
        return node

    def _add_file_node(self, parent: str, label: str, path: str, root_for_rel: str,
                       group: str, default_on: bool = True) -> str:
        node = self.tree.insert(parent, "end", text=f"{CHECK_ON if default_on else CHECK_OFF} {label}", open=False)
        self.item_meta[node] = NodeMeta("file", path, root_for_rel, group, label, selectable=True)
        self.item_state[node] = 1 if default_on else 0
        return node

    def _recompute_parent(self, item: str) -> None:
        parent = self.tree.parent(item)
        if not parent:
            return
        children = self.tree.get_children(parent)
        states = [self.item_state[c] for c in children]
        if all(s == 1 for s in states):
            new = 1
        elif all(s == 0 for s in states):
            new = 0
        else:
            new = 2
        self.item_state[parent] = new
        self._set_item_text(parent, self.item_meta[parent].label, new)
        self._recompute_parent(parent)

    def _set_recursive(self, item: str, on: bool) -> None:
        state = 1 if on else 0
        self.item_state[item] = state
        self._set_item_text(item, self.item_meta[item].label, state)
        for ch in self.tree.get_children(item):
            self._set_recursive(ch, on)

    def _on_space(self, event: tk.Event | None = None) -> None:
        item = self.tree.focus()
        if not item:
            return
        meta = self.item_meta.get(item)
        if not meta or not meta.selectable:
            return
        cur = self.item_state.get(item, 0)
        if meta.kind == "file":
            new = 0 if cur == 1 else 1
            self.item_state[item] = new
            self._set_item_text(item, meta.label, new)
            self._recompute_parent(item)
        else:
            turn_on = (cur != 1)
            self._set_recursive(item, turn_on)
            self._recompute_parent(item)

    def _toggle_all(self, on: bool) -> None:
        self._set_recursive(self.root_item, on)

    def _expand_collapse(self, expand: bool) -> None:
        def walk(it: str) -> None:
            self.tree.item(it, open=expand)
            for c in self.tree.get_children(it):
                walk(c)
        walk(self.root_item)

    def _accept(self) -> None:
        """Devuelve la lista de archivos (absolutos) seleccionados."""
        result: List[str] = []

        def walk(it: str) -> None:
            if self.item_meta[it].kind == "file" and self.item_state[it] == 1:
                result.append(os.path.abspath(self.item_meta[it].path))
            for c in self.tree.get_children(it):
                walk(c)

        walk(self.root_item)
        self.result_paths = result
        self.destroy()

    def _cancel(self) -> None:
        self.result_paths = None
        self.destroy()

    def show(self) -> Optional[List[str]]:
        self.wait_window(self)
        return self.result_paths


# ---------- GUI principal ----------

@dataclass
class ExtraGroupProfile:
    label: str
    files_rel_to_project: List[str]


class DartDumpGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Dart Dump Builder — EXTRAS + lib/")
        self.geometry("1180x720")

        # Estado
        self.item_meta: Dict[str, NodeMeta] = {}
        self.item_state: Dict[str, int] = {}    # 0=off, 1=on, 2=partial (solo dir)
        self.extras_loaded_once: bool = False

        # Mapas para ubicar nodos por ruta (facilita marcar por perfil)
        self.lib_file_nodes: Dict[str, str] = {}      # abs -> item id
        self.extras_file_nodes: Dict[str, str] = {}   # abs -> item id

        # Guardaremos la última vista Y para el scrollbar (evita warnings de tipo)
        self._y_first: float = 0.0
        self._y_last: float = 1.0

        # ---------- MENÚ / PERFILES ----------
        menu = tk.Menu(self)
        self.config(menu=menu)
        profiles_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Perfiles", menu=profiles_menu)
        profiles_menu.add_command(label="Guardar perfil…", command=self.save_profile_dialog)
        profiles_menu.add_command(label="Cargar perfil…", command=self.load_profile_dialog)
        profiles_menu.add_command(label="Borrar perfil…", command=self.delete_profile_dialog)

        # --- TOP ---
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Ruta del proyecto:").grid(row=0, column=0, sticky="w")
        self.project_var = tk.StringVar(value=DEFAULT_PROJECT_ROOT)
        self.project_entry = ttk.Entry(top, textvariable=self.project_var, width=100)
        self.project_entry.grid(row=0, column=1, padx=5, sticky="we")
        ttk.Button(top, text="Examinar…", command=self.pick_project).grid(row=0, column=2, padx=2)

        ttk.Label(top, text="Extensiones (lib):").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.ext_var = tk.StringVar(value=DEFAULT_EXTENSIONS)
        ttk.Entry(top, textvariable=self.ext_var, width=25).grid(row=1, column=1, sticky="w", pady=(6,0))

        ttk.Label(top, text="Excluir carpetas (lib):").grid(row=2, column=0, sticky="w", pady=(6,0))
        self.exclude_var = tk.StringVar(value=DEFAULT_EXCLUDES)
        ttk.Entry(top, textvariable=self.exclude_var, width=50).grid(row=2, column=1, sticky="w", pady=(6,0))

        self.filename_only_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Encabezado solo con nombre de archivo", variable=self.filename_only_var)\
            .grid(row=1, column=2, sticky="w")
        ttk.Checkbutton(top, text="Ver progreso en consola", variable=self.verbose_var)\
            .grid(row=2, column=2, sticky="w")

        ttk.Button(top, text="ESCANEAR", command=self.scan_project).grid(row=0, column=3, rowspan=3, padx=8)

        for i in range(4):
            top.grid_columnconfigure(i, weight=1 if i == 1 else 0)

        # --- CENTRO: Árbol + Scrollbar ---
        mid = ttk.Frame(self, padding=(8,0,8,8))
        mid.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(mid, columns=("dummy",), show="tree")
        yscroll = ttk.Scrollbar(mid, orient="vertical")

        def _tree_yview(*args: Any) -> None:
            if not args:
                return
            op = str(args[0])
            if op == "moveto" and len(args) >= 2:
                try:
                    self.tree.yview_moveto(float(args[1]))
                except Exception:
                    pass
                return
            if op == "scroll" and len(args) >= 3:
                try:
                    count = int(args[1])
                except Exception:
                    count = 0
                token = str(args[2])
                first = self._y_first
                last = self._y_last
                page_step = max(0.0, min(1.0, last - first))
                unit_step = 0.05
                step = page_step if token == "pages" else unit_step
                new_first = max(0.0, min(1.0, first + count * step))
                self.tree.yview_moveto(new_first)

        def _yscroll_set(first: float, last: float) -> None:
            self._y_first, self._y_last = first, last
            yscroll.set(first, last)

        self.tree.configure(yscrollcommand=_yscroll_set)
        yscroll.config(command=_tree_yview)

        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self.on_tree_space)
        self.tree.bind("<space>", self.on_tree_space)
        self.tree.bind("<Return>", self.on_tree_space)

        # Botonera lateral
        right = ttk.Frame(mid)
        right.pack(side="right", fill="y", padx=8)

        ttk.Label(right, text="EXTRAS").pack(anchor="w", pady=(4,2))
        ttk.Button(right, text="Añadir archivo…", command=self.add_extra_file).pack(fill="x", pady=1)
        ttk.Button(right, text="Añadir carpeta (con exclusiones)…", command=self.add_extra_dir_dialog).pack(fill="x", pady=1)
        ttk.Button(right, text="Añadir patrón glob…", command=self.add_extra_glob).pack(fill="x", pady=1)
        ttk.Button(right, text="Quitar extra seleccionado", command=self.remove_extra_selected).pack(fill="x", pady=(1,8))

        ttk.Label(right, text="Selección").pack(anchor="w", pady=(6,2))
        ttk.Button(right, text="Seleccionar todo", command=lambda: self.toggle_all(True)).pack(fill="x", pady=1)
        ttk.Button(right, text="Deseleccionar todo", command=lambda: self.toggle_all(False)).pack(fill="x", pady=1)
        ttk.Button(right, text="Expandir todo", command=lambda: self.expand_collapse_all(True)).pack(fill="x", pady=(8,1))
        ttk.Button(right, text="Colapsar todo", command=lambda: self.expand_collapse_all(False)).pack(fill="x", pady=1)

        # --- BOTTOM ---
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")

        ttk.Label(bottom, text="Guardar TXT en:").grid(row=0, column=0, sticky="w")
        self.out_var = tk.StringVar(value="")
        ttk.Entry(bottom, textvariable=self.out_var, width=100).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(bottom, text="Examinar…", command=self.pick_output).grid(row=0, column=2, padx=2)
        ttk.Button(bottom, text="GENERAR TXT", command=self.generate_txt).grid(row=0, column=3, padx=8)

        for i in range(4):
            bottom.grid_columnconfigure(i, weight=1 if i == 1 else 0)

        # --- Árbol inicial ---
        self.extras_root = self.tree.insert("", "end", text="EXTRAS", open=True)
        self.item_meta[self.extras_root] = NodeMeta("root-extras", "", "", "extras", "EXTRAS", selectable=True)
        self.item_state[self.extras_root] = 1

        self.lib_root_item = self.tree.insert("", "end", text="lib (sin escanear)", open=True)
        self.item_meta[self.lib_root_item] = NodeMeta("root-lib", "", "", "lib", "lib", selectable=True)
        self.item_state[self.lib_root_item] = 1

        tip = ttk.Label(
            self, foreground="#666",
            text="Perfiles → guarda/carga selecciones. Al añadir carpeta puedes excluir subcarpetas/archivos."
        )
        tip.pack(fill="x", padx=8, pady=(0,6))

    # ------------------- Helpers GUI -------------------

    def pick_project(self) -> None:
        path = filedialog.askdirectory(title="Selecciona la carpeta del proyecto")
        if path:
            self.project_var.set(path)

    def pick_output(self) -> None:
        proj = self.project_var.get().strip()
        base = os.path.basename(os.path.normpath(proj)) or "proyecto"
        default_name = f"{base}_dart_sources.txt"
        path = filedialog.asksaveasfilename(
            title="Guardar archivo de texto",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if path:
            self.out_var.set(path)

    def on_tree_space(self, event: tk.Event | None = None) -> None:
        item = self.tree.focus()
        if not item:
            return
        meta = self.item_meta.get(item)
        if not meta or not meta.selectable:
            return
        cur = self.item_state.get(item, 0)
        is_dirlike = meta.kind in {"root-extras", "root-lib", "dir", "extra-group"}
        if is_dirlike:
            self.set_state_recursive(item, cur != 1)
            self.recompute_parent_states(item)
        else:
            new = 0 if cur == 1 else 1
            self.item_state[item] = new
            self.set_item_text(item, meta.label, new)
            self.recompute_parent_states(item)

    def set_item_text(self, item: str, base: str, state: int) -> None:
        prefix = CHECK_OFF if state == 0 else CHECK_ON if state == 1 else CHECK_PARTIAL
        self.tree.item(item, text=f"{prefix} {base}")

    def set_state_recursive(self, item: str, on: bool) -> None:
        state = 1 if on else 0
        self.item_state[item] = state
        base = self.item_meta[item].label
        self.set_item_text(item, base, state)
        for child in self.tree.get_children(item):
            self.set_state_recursive(child, on)

    def recompute_parent_states(self, item: str) -> None:
        parent = self.tree.parent(item)
        if not parent:
            return
        children = self.tree.get_children(parent)
        states = [self.item_state[c] for c in children]
        if all(s == 1 for s in states):
            new = 1
        elif all(s == 0 for s in states):
            new = 0
        else:
            new = 2
        self.item_state[parent] = new
        self.set_item_text(parent, self.item_meta[parent].label, new)
        self.recompute_parent_states(parent)

    def toggle_all(self, on: bool) -> None:
        for root in (self.extras_root, self.lib_root_item):
            self.set_state_recursive(root, on)

    def expand_collapse_all(self, expand: bool) -> None:
        def _walk(it: str) -> None:
            self.tree.item(it, open=expand)
            for ch in self.tree.get_children(it):
                _walk(ch)
        _walk(self.extras_root)
        _walk(self.lib_root_item)

    # ------------------- Escaneo -------------------

    def parse_exts(self) -> Set[str]:
        raw = self.ext_var.get().strip()
        if not raw:
            return {"dart"}
        return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}

    def parse_excludes(self) -> Set[str]:
        raw = self.exclude_var.get().strip()
        if not raw:
            return set()
        return {e.strip() for e in raw.split(",") if e.strip()}

    def clear_children(self, item: str) -> None:
        for ch in self.tree.get_children(item):
            self.tree.delete(ch)

    def add_dir_node(self, parent: str, label: str, path: str, root_for_rel: str, group: str) -> str:
        node = self.tree.insert(parent, "end", text=f"{CHECK_ON} {label}", open=False)
        self.item_meta[node] = NodeMeta("dir", path, root_for_rel, group, label, selectable=True)
        self.item_state[node] = 1
        return node

    def add_file_node(self, parent: str, label: str, path: str, root_for_rel: str,
                      group: str, default_on: bool = True) -> str:
        node = self.tree.insert(parent, "end", text=f"{CHECK_ON if default_on else CHECK_OFF} {label}", open=False)
        self.item_meta[node] = NodeMeta("file", path, root_for_rel, group, label, selectable=True)
        self.item_state[node] = 1 if default_on else 0
        absn = os.path.normcase(os.path.abspath(path))
        if group == "lib":
            self.lib_file_nodes[absn] = node
        else:
            self.extras_file_nodes[absn] = node
        return node

    def scan_project(self) -> None:
        project_root = self.project_var.get().strip()
        if not project_root or not os.path.isdir(project_root):
            messagebox.showerror("Error", "Selecciona una ruta de proyecto válida.")
            return

        lib_path = os.path.join(project_root, "lib")
        if not os.path.isdir(lib_path):
            messagebox.showerror("Error", "No se encontró la carpeta 'lib' en el proyecto.")
            return

        # Reset mapas
        self.lib_file_nodes.clear()

        # Preparar lib root
        self.tree.item(self.lib_root_item, text="lib")
        self.item_meta[self.lib_root_item] = NodeMeta("root-lib", lib_path, lib_path, "lib", "lib", selectable=True)
        self.item_state[self.lib_root_item] = 1
        self.clear_children(self.lib_root_item)

        allowed_exts = self.parse_exts()
        excludes = self.parse_excludes()

        entries = os.listdir(lib_path)

        # 1) Archivos en lib/
        top_files = [e for e in entries if os.path.isfile(os.path.join(lib_path, e))]
        for f in sorted_casefold(top_files):
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in allowed_exts:
                self.add_file_node(self.lib_root_item, f, os.path.join(lib_path, f), lib_path, "lib", default_on=True)

        # 2) Subcarpetas
        top_dirs = [e for e in entries if os.path.isdir(os.path.join(lib_path, e))]
        for d in sorted_casefold(top_dirs):
            if d in excludes:
                continue
            dir_path = os.path.join(lib_path, d)
            node = self.add_dir_node(self.lib_root_item, d, dir_path, lib_path, "lib")
            self.populate_lib_dir(node, dir_path, lib_path, allowed_exts, excludes)

        # EXTRAS por defecto solo la primera vez
        if not self.extras_loaded_once:
            self.ensure_default_extras(project_root)
            self.extras_loaded_once = True

        self.tree.item(self.extras_root, open=True)
        self.tree.item(self.lib_root_item, open=True)

    def populate_lib_dir(self, parent: str, dir_path: str, lib_root: str,
                         allowed_exts: Set[str], excludes: Set[str]) -> None:
        try:
            entries = os.listdir(dir_path)
        except PermissionError:
            return

        files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e))]
        for f in sorted_casefold(files):
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in allowed_exts:
                self.add_file_node(parent, f, os.path.join(dir_path, f), lib_root, "lib", default_on=True)

        dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
        for d in sorted_casefold(dirs):
            if d in excludes:
                continue
            dpath = os.path.join(dir_path, d)
            node = self.add_dir_node(parent, d, dpath, lib_root, "lib")
            self.populate_lib_dir(node, dpath, lib_root, allowed_exts, excludes)

        self.recompute_parent_states(parent)

    # ------------------- EXTRAS -------------------

    def ensure_default_extras(self, project_root: str) -> None:
        # Limpia EXTRAS y crea los defaults
        self.clear_children(self.extras_root)
        self.extras_file_nodes.clear()

        extras: List[Dict[str, Any]] = [
            {"label": "pubspec", "files": [os.path.join(project_root, "pubspec.yaml")]}
        ]
        for extra in extras:
            label: str = str(extra.get("label", "Extras"))
            group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label}]", open=True)
            self.item_meta[group_node] = NodeMeta("extra-group", "", project_root, "extras-group", f"[{label}]", selectable=True)
            self.item_state[group_node] = 1
            for f in list(extra.get("files", [])):
                f = str(f)
                lbl: str = os.path.relpath(f, project_root).replace(os.sep, "/") if os.path.isabs(f) else f
                self.add_file_node(group_node, lbl, os.path.abspath(f), project_root, "extras", default_on=True)

        self.recompute_parent_states(self.extras_root)

    def add_extra_file(self) -> None:
        proj = self.project_var.get().strip()
        initial = proj if os.path.isdir(proj) else os.getcwd()
        path = filedialog.askopenfilename(title="Elegir archivo EXTRA", initialdir=initial)
        if not path:
            return
        label_group = simpledialog.askstring("Etiqueta", "Etiqueta para este EXTRA (ej. readme, config):", parent=self)
        label_group = label_group or os.path.basename(path)
        group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label_group}]", open=True)
        self.item_meta[group_node] = NodeMeta("extra-group", "", proj, "extras-group", f"[{label_group}]", selectable=True)
        self.item_state[group_node] = 1
        self.add_file_node(group_node, os.path.relpath(path, proj).replace(os.sep, "/"),
                           os.path.abspath(path), proj, "extras", default_on=True)
        self.recompute_parent_states(self.extras_root)

    def add_extra_dir_dialog(self) -> None:
        proj = self.project_var.get().strip()
        base = filedialog.askdirectory(title="Elegir carpeta EXTRA", initialdir=proj if os.path.isdir(proj) else os.getcwd())
        if not base:
            return
        exts = simpledialog.askstring("Extensiones", "Filtrar por extensiones (coma) o vacío para todas:", parent=self)
        allowed = {e.strip().lower().lstrip(".") for e in exts.split(",")} if exts else None

        dlg = SelectFromFolderDialog(self, base, allowed)
        selected = dlg.show()
        if not selected:
            return

        label_group = simpledialog.askstring("Etiqueta", "Etiqueta para la carpeta EXTRA:", parent=self)
        label_group = label_group or os.path.basename(base)

        group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label_group}]", open=True)
        self.item_meta[group_node] = NodeMeta("extra-group", "", proj, "extras-group", f"[{label_group}]", selectable=True)
        self.item_state[group_node] = 1

        # Añadir con jerarquía anidada real
        path_to_node: Dict[str, str] = {"": group_node}
        for abs_path in sorted(selected, key=lambda p: p.casefold()):
            rel = os.path.relpath(abs_path, proj).replace(os.sep, "/")
            parts = rel.split("/")
            cur_parent = group_node
            running_dir = ""
            for part in parts[:-1]:
                running_dir = f"{running_dir}/{part}" if running_dir else part
                if running_dir not in path_to_node:
                    node = self.add_dir_node(cur_parent, part, os.path.join(proj, running_dir), proj, "extras")
                    path_to_node[running_dir] = node
                    cur_parent = node
                else:
                    cur_parent = path_to_node[running_dir]
            # archivo
            self.add_file_node(cur_parent, parts[-1], abs_path, proj, "extras", default_on=True)

        self.recompute_parent_states(self.extras_root)

    def add_extra_glob(self) -> None:
        proj = self.project_var.get().strip()
        patt = simpledialog.askstring("Patrón glob", "Patrón relativo al proyecto (ej: test/**/*.dart):", parent=self)
        if not patt:
            return
        label_group = simpledialog.askstring("Etiqueta", "Etiqueta para este patrón:", parent=self) or patt
        base = os.path.join(proj, patt)
        matches = _glob.glob(base, recursive=True)

        group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label_group}]", open=True)
        self.item_meta[group_node] = NodeMeta("extra-group", "", proj, "extras-group", f"[{label_group}]", selectable=True)
        self.item_state[group_node] = 1

        if not matches:
            empty = self.add_file_node(group_node, f"{patt} [SIN COINCIDENCIAS]", base, proj, "extras", default_on=False)
            self.item_meta[empty].selectable = False
        else:
            for m in sorted_casefold([p for p in matches if os.path.isfile(p)]):
                self.add_file_node(group_node, os.path.relpath(m, proj).replace(os.sep, "/"),
                                   os.path.abspath(m), proj, "extras", default_on=True)
        self.recompute_parent_states(self.extras_root)

    def remove_extra_selected(self) -> None:
        item = self.tree.focus()
        if not item:
            messagebox.showinfo("Info", "Selecciona un nodo dentro de EXTRAS para eliminar.")
            return
        # solo permite eliminar bajo EXTRAS
        parent_chain: List[str] = []
        cur: Optional[str] = item
        while cur:
            parent_chain.append(cur)
            cur = self.tree.parent(cur)
        if self.extras_root not in parent_chain:
            messagebox.showinfo("Info", "Solo puedes eliminar elementos del árbol EXTRAS.")
            return
        if item == self.extras_root:
            messagebox.showwarning("Aviso", "No puedes eliminar el nodo raíz EXTRAS.")
            return
        self.tree.delete(item)

    # ------------------- Recolección / escritura -------------------

    def gather_selected_files(self, root_item: str) -> List[Tuple[str, str]]:
        """Devuelve lista (abs_path, root_for_rel) en orden del árbol para items 'file' seleccionados."""
        result: List[Tuple[str, str]] = []

        def walk(it: str) -> None:
            state = self.item_state.get(it, 0)
            meta = self.item_meta.get(it)
            if not meta:
                return
            if meta.kind == "file" and state == 1:
                result.append((os.path.abspath(meta.path), meta.root_for_rel))
            for ch in self.tree.get_children(it):
                walk(ch)

        walk(root_item)
        return result

    def generate_txt(self) -> None:
        project_root = self.project_var.get().strip()
        if not project_root or not os.path.isdir(project_root):
            messagebox.showerror("Error", "Selecciona una ruta de proyecto válida.")
            return

        lib_path = os.path.join(project_root, "lib")
        if not os.path.isdir(lib_path):
            messagebox.showerror("Error", "No se encontró la carpeta 'lib' en el proyecto.")
            return

        out_path = self.out_var.get().strip()
        if not out_path:
            base = os.path.basename(os.path.normpath(project_root)) or "proyecto"
            out_path = os.path.join(os.getcwd(), f"{base}_dart_sources.txt")

        extras_files = self.gather_selected_files(self.extras_root)
        lib_files = self.gather_selected_files(self.lib_root_item)
        lib_selected_set: Set[str] = {os.path.normcase(os.path.abspath(p)) for (p, _) in lib_files}

        filename_only = self.filename_only_var.get()
        verbose = self.verbose_var.get()
        excludes = self.parse_excludes()

        if verbose:
            print("—" * 80)
            print("Generando archivo…")
            print(f"Salida: {out_path}")
            print(f"Extras seleccionados: {len(extras_files)} | Archivos lib seleccionados: {len(lib_files)}")

        try:
            with open(out_path, "w", encoding="utf-8") as out_fh:
                out_fh.write(f"PROYECTO: {project_root}\n")
                out_fh.write(f"LIB: {lib_path}\n")
                out_fh.write("=" * 80 + "\n\n")

                # EXTRAS primero
                if extras_files:
                    out_fh.write("EXTRAS (inicio)\n")
                    out_fh.write("=" * 80 + "\n\n")
                    for abs_path, root_for_rel in extras_files:
                        write_file_block(out_fh, abs_path, root_for_rel, filename_only)

                # Helpers para lib con encabezados solo si hay seleccionados
                def subtree_has_selected(path: str) -> bool:
                    try:
                        entries = os.listdir(path)
                    except PermissionError:
                        return False
                    for f in entries:
                        p = os.path.join(path, f)
                        if os.path.isfile(p) and os.path.normcase(os.path.abspath(p)) in lib_selected_set:
                            return True
                    for d in entries:
                        p = os.path.join(path, d)
                        if os.path.isdir(p) and d not in excludes:
                            if subtree_has_selected(p):
                                return True
                    return False

                def write_descend(cur: str, rel_parts: List[str]) -> None:
                    try:
                        entries = os.listdir(cur)
                    except PermissionError:
                        return
                    # archivos
                    files = [e for e in entries if os.path.isfile(os.path.join(cur, e))]
                    for f in sorted_casefold(files):
                        fpath = os.path.join(cur, f)
                        if os.path.normcase(os.path.abspath(fpath)) in lib_selected_set:
                            write_file_block(out_fh, fpath, lib_path, filename_only)
                    # subdirs
                    dirs = [e for e in entries if os.path.isdir(os.path.join(cur, e))]
                    for subd in sorted_casefold(dirs):
                        if subd in excludes:
                            continue
                        subpath = os.path.join(cur, subd)
                        if not subtree_has_selected(subpath):
                            continue
                        out_fh.write(dir_header(len(rel_parts) + 1, subd))
                        out_fh.write("\n")
                        write_descend(subpath, rel_parts + [subd])

                # 1) top-level files en lib
                top_entries = os.listdir(lib_path)
                top_files = [e for e in top_entries if os.path.isfile(os.path.join(lib_path, e))]
                for f in sorted_casefold(top_files):
                    fpath = os.path.join(lib_path, f)
                    if os.path.normcase(os.path.abspath(fpath)) in lib_selected_set:
                        write_file_block(out_fh, fpath, lib_path, filename_only)

                # 2) subcarpetas con encabezados
                top_dirs = [e for e in top_entries if os.path.isdir(os.path.join(lib_path, e))]
                for d in sorted_casefold(top_dirs):
                    if d in excludes:
                        continue
                    dpath = os.path.join(lib_path, d)
                    if not subtree_has_selected(dpath):
                        continue
                    out_fh.write(dir_header(1, d))
                    out_fh.write("\n")
                    write_descend(dpath, [d])

            if verbose:
                print("✅ TXT generado correctamente.")
            messagebox.showinfo("Listo", f"Archivo generado:\n{out_path}")

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el TXT:\n{e}")
            if verbose:
                raise

    # ------------------- Perfiles -------------------

    def build_profile_payload(self) -> Dict[str, Any]:
        """Crea un payload con opciones + selección actual."""
        proj = os.path.abspath(self.project_var.get().strip())

        # Lib seleccionados
        lib_selected_rel: List[str] = []
        for abs_path, _ in self.gather_selected_files(self.lib_root_item):
            lib_selected_rel.append(os.path.relpath(abs_path, proj).replace(os.sep, "/"))

        # Extras agrupados (buscamos el ancestro "extra-group")
        extras_by_group: Dict[str, List[str]] = {}

        def walk(it: str, current_group: Optional[str]) -> None:
            meta = self.item_meta[it]
            base_group = current_group
            if meta.kind == "extra-group":
                base_group = meta.label.strip()
                if base_group.startswith("[") and base_group.endswith("]"):
                    base_group = base_group[1:-1]
            if meta.kind == "file" and self.item_state[it] == 1 and meta.group != "lib":
                rel = os.path.relpath(meta.path, proj).replace(os.sep, "/")
                extras_by_group.setdefault(base_group or "Extras", []).append(rel)
            for ch in self.tree.get_children(it):
                walk(ch, base_group)

        for ch in self.tree.get_children(self.extras_root):
            walk(ch, None)

        payload: Dict[str, Any] = {
            "project_root": proj,
            "options": {
                "extensions": self.ext_var.get().strip(),
                "excludes": self.exclude_var.get().strip(),
                "filename_only": self.filename_only_var.get(),
                "verbose": self.verbose_var.get(),
            },
            "lib_selected": lib_selected_rel,
            "extras_groups": [
                {"label": lbl, "files": files} for lbl, files in extras_by_group.items()
            ],
        }
        return payload

    def apply_profile_payload(self, payload: Dict[str, Any]) -> None:
        """Aplica un perfil completo."""
        proj = str(payload.get("project_root") or self.project_var.get())
        self.project_var.set(proj)
        opts: Dict[str, Any] = dict(payload.get("options", {}))
        self.ext_var.set(str(opts.get("extensions", self.ext_var.get())))
        self.exclude_var.set(str(opts.get("excludes", self.exclude_var.get())))
        self.filename_only_var.set(bool(opts.get("filename_only", False)))
        self.verbose_var.set(bool(opts.get("verbose", True)))

        # escanear
        self.scan_project()

        # reconstruir EXTRAS desde perfil
        self.clear_children(self.extras_root)
        self.extras_file_nodes.clear()

        extras_groups: List[Dict[str, Any]] = list(payload.get("extras_groups", []))
        for group in extras_groups:
            label = str(group.get("label") or "Extras")
            files_rel: List[str] = list(group.get("files") or [])
            group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label}]", open=True)
            self.item_meta[group_node] = NodeMeta("extra-group", "", proj, "extras-group", f"[{label}]", selectable=True)
            self.item_state[group_node] = 1

            # crear jerarquía
            path_to_node: Dict[str, str] = {"": group_node}
            for rel in sorted(files_rel, key=lambda p: p.casefold()):
                abs_path = os.path.abspath(os.path.join(proj, rel))
                parts = rel.replace("\\", "/").split("/")
                cur_parent = group_node
                running_dir = ""
                for part in parts[:-1]:
                    running_dir = f"{running_dir}/{part}" if running_dir else part
                    if running_dir not in path_to_node:
                        node = self.add_dir_node(cur_parent, part, os.path.join(proj, running_dir), proj, "extras")
                        path_to_node[running_dir] = node
                        cur_parent = node
                    else:
                        cur_parent = path_to_node[running_dir]
                # archivo (si no existe, lo marcamos no seleccionable)
                if os.path.isfile(abs_path):
                    self.add_file_node(cur_parent, parts[-1], abs_path, proj, "extras", default_on=True)
                else:
                    missing = self.add_file_node(cur_parent, parts[-1] + " [NO ENCONTRADO]", abs_path, proj, "extras", default_on=False)
                    self.item_meta[missing].selectable = False

        self.recompute_parent_states(self.extras_root)

        # seleccionar lib segun perfil
        for it in self.tree.get_children(self.lib_root_item):
            self.set_state_recursive(it, False)

        proj_abs = os.path.abspath(proj)
        for rel in list(payload.get("lib_selected", [])):
            rel = str(rel)
            absn = os.path.normcase(os.path.abspath(os.path.join(proj_abs, rel)))
            node = self.lib_file_nodes.get(absn)
            if node:
                self.item_state[node] = 1
                self.set_item_text(node, self.item_meta[node].label, 1)
                self.recompute_parent_states(node)

    # ---- acciones menú perfiles ----

    def save_profile_dialog(self) -> None:
        store = _load_profile_store()
        name = simpledialog.askstring("Guardar perfil", "Nombre del perfil:", parent=self)
        if not name:
            return
        payload: Dict[str, Any] = self.build_profile_payload()
        store[name] = payload
        _save_profile_store(store)
        messagebox.showinfo("Perfiles", f"Perfil '{name}' guardado.")

    def load_profile_dialog(self) -> None:
        store = _load_profile_store()
        if not store:
            messagebox.showinfo("Perfiles", "No hay perfiles guardados.")
            return
        names = sorted(store.keys(), key=str.casefold)
        name = simpledialog.askstring("Cargar perfil", f"Perfiles disponibles:\n- " + "\n- ".join(names) + "\n\nEscribe el nombre exacto:", parent=self)
        if not name or name not in store:
            return
        self.apply_profile_payload(store[name])
        messagebox.showinfo("Perfiles", f"Perfil '{name}' cargado.")

    def delete_profile_dialog(self) -> None:
        store = _load_profile_store()
        if not store:
            messagebox.showinfo("Perfiles", "No hay perfiles guardados.")
            return
        names = sorted(store.keys(), key=str.casefold)
        name = simpledialog.askstring("Borrar perfil", f"Perfiles disponibles:\n- " + "\n- ".join(names) + "\n\nEscribe el nombre a borrar:", parent=self)
        if not name or name not in store:
            return
        if not messagebox.askyesno("Confirmar", f"¿Borrar el perfil '{name}'?"):
            return
        del store[name]
        _save_profile_store(store)
        messagebox.showinfo("Perfiles", f"Perfil '{name}' borrado.")


# ---------- main ----------

if __name__ == "__main__":
    try:
        app = DartDumpGUI()
        app.mainloop()
    except tk.TclError as e:
        sys.stderr.write(
            "ERROR: No se pudo iniciar Tkinter.\n"
            "Instala Python oficial (tk incluido) o el paquete correspondiente a tu OS.\n"
            f"Detalle: {e}\n"
        )
        sys.exit(1)
