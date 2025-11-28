#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dart Dump Builder (GUI) — multi-perfiles, salida personalizable, raíces múltiples y preferencias
-----------------------------------------------------------------------------------------------
• Raíces fuente configurables (p. ej., lib, src, app, packages, etc.).
• EXTRAS: archivo, glob o carpeta con diálogo para excluir subcarpetas/archivos.
• Perfiles:
    - Guardar / Cargar (combobox y diálogos con lista; sin escribir nombres).
    - Activar varios perfiles a la vez (fusión por unión) con panel visible de “Perfiles activos”.
• Salida personalizable:
    - Modos: Contenido (selección) [DEFAULT] / Solo estructura / Selección + resto estructura.
    - Separador por archivo: carácter, ancho fijo o auto, y marcador END opcional.
• Preferencias globales persistentes (JSON): raíces, extensiones, exclusiones, salida, separadores, etc.

Probado con Python 3.13.9.
"""

from __future__ import annotations

import json
import os
import sys
import glob as _glob
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, TextIO, Tuple, cast, TypedDict

# --- Tkinter ---
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# =================== CONFIG GLOBAL ===================

DEFAULT_PROJECT_ROOT: str = (
    "C:/Users/marqu/Programacion/App100MujeresTrabajando/flutter_application_emprendedoras"
)

DEFAULT_SOURCE_ROOTS: str = "lib"           # ahora múltiple: "lib,src,app"
DEFAULT_EXTENSIONS: str = "dart"            # extensiones (coma) p/raíz (todas iguales por ahora)
DEFAULT_EXCLUDES: str = ".git,build,.dart_tool,.idea,.vscode"

PROFILE_STORE: str = os.path.expanduser("~/.dart_dump_gui_profiles.json")
PREFS_STORE: str = os.path.expanduser("~/.dart_dump_gui_prefs.json")

# ---------------- Tipado de preferencias ----------------

class Prefs(TypedDict, total=False):
    project_root: str
    source_roots: str
    extensions: str
    excludes: str
    filename_only: bool
    verbose: bool
    output_mode: str
    sep_char: str
    sep_width: int
    sep_auto: bool
    sep_print_end: bool

# =====================================================

def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def _save_json(path: str, data: Dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        # messagebox puede no existir en entornos sin GUI; protegemos
        try:
            messagebox.showwarning("Aviso", f"No se pudo guardar en {path}:\n{e}")
        except Exception:
            sys.stderr.write(f"[WARN] No se pudo guardar en {path}: {e}\n")

def _load_profile_store() -> Dict[str, Any]:
    return _load_json(PROFILE_STORE)

def _save_profile_store(store: Dict[str, Any]) -> None:
    _save_json(PROFILE_STORE, store)

def _load_prefs() -> Prefs:
    data: Dict[str, Any] = _load_json(PREFS_STORE)
    prefs: Prefs = {}
    if "project_root" in data:     prefs["project_root"] = str(data["project_root"])
    if "source_roots" in data:     prefs["source_roots"] = str(data["source_roots"])
    if "extensions" in data:       prefs["extensions"] = str(data["extensions"])
    if "excludes" in data:         prefs["excludes"] = str(data["excludes"])
    if "filename_only" in data:    prefs["filename_only"] = bool(data["filename_only"])
    if "verbose" in data:          prefs["verbose"] = bool(data["verbose"])
    if "output_mode" in data:      prefs["output_mode"] = str(data["output_mode"])
    if "sep_char" in data:         prefs["sep_char"] = str(data["sep_char"])[:1] or "-"
    if "sep_width" in data:        prefs["sep_width"] = int(data["sep_width"])
    if "sep_auto" in data:         prefs["sep_auto"] = bool(data["sep_auto"])
    if "sep_print_end" in data:    prefs["sep_print_end"] = bool(data["sep_print_end"])
    return prefs

def _save_prefs(prefs: Prefs) -> None:
    _save_json(PREFS_STORE, dict(prefs))

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

CHECK_OFF = "☐"
CHECK_ON = "☑"
CHECK_PARTIAL = "◩"

@dataclass
class NodeMeta:
    kind: str              # "root-extras" | "root-srcroot" | "dir" | "file" | "extra-group"
    path: str              # absoluta si aplica
    root_for_rel: str      # base para rutas relativas
    group: str             # "extras" | "<srcroot>" | "extras-group" | "dialog"
    label: str             # texto sin prefijo
    selectable: bool = True

# ---------- Diálogo selector de carpeta (pre-exclusiones) ----------

class SelectFromFolderDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, base_dir: str, ext_filter: Optional[Set[str]] = None,
                 title: str = "Seleccionar desde carpeta") -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("800x520")
        self.resizable(True, True)
        try:
            self.transient(master)  # type: ignore[arg-type]
        except Exception:
            pass
        self.grab_set()

        self.base_dir = os.path.abspath(base_dir)
        self.ext_filter = {e.lower().lstrip(".") for e in (ext_filter or set())} or None

        self.item_state: Dict[str, int] = {}
        self.item_meta: Dict[str, NodeMeta] = {}
        self.result_paths: Optional[List[str]] = None

        # Top
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text=f"Carpeta base: {self.base_dir}").pack(anchor="w")

        # Centro
        mid = ttk.Frame(self, padding=(6, 0, 6, 6))
        mid.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(mid, columns=("dummy",), show="tree")
        yscroll = ttk.Scrollbar(mid, orient="vertical")

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

        # Árbol
        base_label = os.path.basename(self.base_dir.strip("\\/")) or self.base_dir
        self.root_item = self._add_dir_node("", base_label, self.base_dir, self.base_dir, "dialog")
        path_to_node: Dict[str, str] = {self.base_dir: self.root_item}

        for root, dirs, files in os.walk(self.base_dir, topdown=True):
            dirs[:] = sorted_casefold(dirs)
            files = sorted_casefold(files)
            parent_node = path_to_node.get(root, self.root_item)

            for d in dirs:
                dpath = os.path.join(root, d)
                node = self._add_dir_node(parent_node, d, dpath, self.base_dir, "dialog")
                path_to_node[dpath] = node

            for f in files:
                if self.ext_filter is not None:
                    ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                    if ext not in self.ext_filter:
                        continue
                fpath = os.path.join(root, f)
                self._add_file_node(parent_node, f, fpath, self.base_dir, "dialog", default_on=True)

        self.tree.item(self.root_item, open=True)

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

# ---------------- GUI principal ----------------

@dataclass
class ExtraGroupProfile:
    label: str
    files_rel_to_project: List[str]

class DartDumpGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Dart Dump Builder — EXTRAS + raíces múltiples")
        self.geometry("1280x820")

        # Estado
        self.item_meta: Dict[str, NodeMeta] = {}
        self.item_state: Dict[str, int] = {}
        self.extras_loaded_once: bool = False
        self.src_roots_nodes: Dict[str, str] = {}  # root_name -> tree item id
        self.src_root_files_nodes: Dict[str, Dict[str, str]] = {}  # root_name -> (abs -> item id)
        self.extras_file_nodes: Dict[str, str] = {}
        self.active_profiles: List[str] = []

        self._y_first: float = 0.0
        self._y_last: float = 1.0

        # ---------- TOP BAR ----------
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        # Carga preferencias si existen
        prefs = _load_prefs()
        project_def = prefs.get("project_root", DEFAULT_PROJECT_ROOT)
        roots_def = prefs.get("source_roots", DEFAULT_SOURCE_ROOTS)
        exts_def = prefs.get("extensions", DEFAULT_EXTENSIONS)
        excl_def = prefs.get("excludes", DEFAULT_EXCLUDES)
        filename_only_def = bool(prefs.get("filename_only", False))
        verbose_def = bool(prefs.get("verbose", True))
        output_mode_def = prefs.get("output_mode", "content_selected")
        sep_char_def = prefs.get("sep_char", "-")
        sep_width_def = int(prefs.get("sep_width", 80))
        sep_auto_def = bool(prefs.get("sep_auto", False))
        sep_end_def = bool(prefs.get("sep_print_end", True))

        ttk.Label(top, text="Proyecto:").grid(row=0, column=0, sticky="w")
        self.project_var = tk.StringVar(value=project_def)
        self.project_entry = ttk.Entry(top, textvariable=self.project_var, width=82)
        self.project_entry.grid(row=0, column=1, padx=5, sticky="we")
        ttk.Button(top, text="Examinar…", command=self.pick_project).grid(row=0, column=2, padx=2)

        ttk.Label(top, text="Raíces fuente (coma):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.roots_var = tk.StringVar(value=roots_def)
        ttk.Entry(top, textvariable=self.roots_var, width=48).grid(row=1, column=1, sticky="w", pady=(6, 0))

        ttk.Label(top, text="Extensiones:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.ext_var = tk.StringVar(value=exts_def)
        ttk.Entry(top, textvariable=self.ext_var, width=24).grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(top, text="Excluir carpetas:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.exclude_var = tk.StringVar(value=excl_def)
        ttk.Entry(top, textvariable=self.exclude_var, width=48).grid(row=3, column=1, sticky="w", pady=(6, 0))

        self.filename_only_var = tk.BooleanVar(value=filename_only_def)
        self.verbose_var = tk.BooleanVar(value=verbose_def)
        ttk.Checkbutton(top, text="Encabezado solo nombre de archivo", variable=self.filename_only_var)\
            .grid(row=2, column=2, sticky="w")
        ttk.Checkbutton(top, text="Ver progreso en consola", variable=self.verbose_var)\
            .grid(row=3, column=2, sticky="w")

        ttk.Button(top, text="ESCANEAR", command=self.scan_project).grid(row=0, column=3, rowspan=4, padx=8)

        # Perfiles (carga rápida + estado)
        ttk.Label(top, text="Perfil rápido:").grid(row=4, column=0, sticky="w", pady=(8,0))
        self.profile_combo = ttk.Combobox(top, state="readonly", values=self._profile_names(), width=40)
        self.profile_combo.grid(row=4, column=1, sticky="w", pady=(8,0))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_quick_profile_selected)
        self.profile_status_var = tk.StringVar(value="Perfiles activos: (ninguno)")
        ttk.Label(top, textvariable=self.profile_status_var, foreground="#555").grid(row=4, column=2, columnspan=2, sticky="w", padx=(8,0))

        for i in range(4):
            top.grid_columnconfigure(i, weight=1 if i == 1 else 0)

        # ---------- MID: Árbol + Lado derecho ----------
        mid = ttk.Frame(self, padding=(8, 0, 8, 8))
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

        # Lado derecho: EXTRAS + Perfiles + Salida + Separadores + Preferencias
        right = ttk.Frame(mid)
        right.pack(side="right", fill="y", padx=8)

        # --- EXTRAS ---
        extras_box = ttk.LabelFrame(right, text="EXTRAS", padding=8)
        extras_box.pack(fill="x", pady=(4, 6))
        ttk.Button(extras_box, text="Añadir archivo…", command=self.add_extra_file).pack(fill="x", pady=1)
        ttk.Button(extras_box, text="Añadir carpeta (con exclusiones)…", command=self.add_extra_dir_dialog).pack(fill="x", pady=1)
        ttk.Button(extras_box, text="Añadir patrón glob…", command=self.add_extra_glob).pack(fill="x", pady=1)
        ttk.Button(extras_box, text="Quitar extra seleccionado", command=self.remove_extra_selected).pack(fill="x", pady=(1, 0))

        # --- Perfiles visibles ---
        prof_box = ttk.LabelFrame(right, text="Perfiles", padding=8)
        prof_box.pack(fill="x", pady=(6, 6))
        ttk.Button(prof_box, text="Guardar…", command=self.save_profile_dialog).pack(fill="x", pady=1)
        ttk.Button(prof_box, text="Cargar…", command=self.load_profile_dialog).pack(fill="x", pady=1)
        ttk.Button(prof_box, text="Activar (multi)…", command=self.activate_profiles_dialog).pack(fill="x", pady=1)
        ttk.Button(prof_box, text="Borrar…", command=self.delete_profile_dialog).pack(fill="x", pady=1)

        # Panel “Perfiles activos (fusión)”
        active_box = ttk.LabelFrame(right, text="Perfiles activos (fusión)", padding=8)
        active_box.pack(fill="x", pady=(2, 6))
        self.active_list = tk.Listbox(active_box, height=5)
        self.active_list.pack(fill="x")
        ttk.Button(active_box, text="Desactivar todos", command=self._clear_active_profiles).pack(fill="x", pady=(6,0))

        # --- Controles de salida ---
        out_box = ttk.LabelFrame(right, text="Salida", padding=8)
        out_box.pack(fill="x", pady=(6, 2))

        self.output_mode_var = tk.StringVar(value=output_mode_def)
        ttk.Radiobutton(out_box, text="Contenido (selección)", value="content_selected",
                        variable=self.output_mode_var).pack(anchor="w")
        ttk.Radiobutton(out_box, text="Solo estructura (sin contenido)", value="structure_only",
                        variable=self.output_mode_var).pack(anchor="w")
        ttk.Radiobutton(out_box, text="Selección con contenido + resto estructura",
                        value="selected_plus_structure", variable=self.output_mode_var).pack(anchor="w")

        # --- Separadores ---
        sep_box = ttk.LabelFrame(right, text="Separadores", padding=8)
        sep_box.pack(fill="x", pady=(6, 2))
        ttk.Label(sep_box, text="Carácter:").grid(row=0, column=0, sticky="w")
        self.sep_char_var = tk.StringVar(value=sep_char_def)
        ttk.Entry(sep_box, textvariable=self.sep_char_var, width=4).grid(row=0, column=1, sticky="w", padx=(4,8))

        ttk.Label(sep_box, text="Ancho:").grid(row=0, column=2, sticky="w")
        self.sep_width_var = tk.IntVar(value=sep_width_def)
        ttk.Spinbox(sep_box, from_=20, to=200, textvariable=self.sep_width_var, width=6).grid(row=0, column=3, sticky="w", padx=(4,8))

        self.sep_auto_var = tk.BooleanVar(value=sep_auto_def)
        ttk.Checkbutton(sep_box, text="Auto ancho", variable=self.sep_auto_var).grid(row=0, column=4, sticky="w")

        self.sep_end_var = tk.BooleanVar(value=sep_end_def)
        ttk.Checkbutton(sep_box, text="Imprimir END", variable=self.sep_end_var).grid(row=1, column=0, columnspan=5, sticky="w", pady=(6,0))

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

        ttk.Label(self, foreground="#666",
                  text="Tip: ‘Activar (multi)’ fusiona perfiles (unión). La lista ‘Perfiles activos’ muestra los aplicados.")\
            .pack(fill="x", padx=8, pady=(0, 6))

        # Menú Preferencias
        menu = tk.Menu(self)
        self.config(menu=menu)
        pref_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Preferencias", menu=pref_menu)
        pref_menu.add_command(label="Guardar como predeterminadas", command=self.save_prefs)
        pref_menu.add_command(label="Restaurar predeterminadas", command=self.restore_prefs)

    # ------------------- Helpers GUI -------------------

    def _profile_names(self) -> List[str]:
        return sorted(_load_profile_store().keys(), key=str.casefold)

    def _on_quick_profile_selected(self, event: tk.Event | None) -> None:
        name = self.profile_combo.get().strip()
        if not name:
            return
        store = _load_profile_store()
        if name in store:
            self.apply_profile_payload(store[name])
            self.active_profiles = [name]
            self._refresh_profile_ui()

    def _refresh_profile_ui(self) -> None:
        self.profile_combo["values"] = self._profile_names()
        self.profile_status_var.set(
            "Perfiles activos: " + (", ".join(self.active_profiles) if self.active_profiles else "(ninguno)")
        )
        # Pinta listbox
        self.active_list.delete(0, tk.END)
        for n in self.active_profiles:
            self.active_list.insert(tk.END, n)

    def _clear_active_profiles(self) -> None:
        self.active_profiles = []
        self._refresh_profile_ui()

    def pick_project(self) -> None:
        path = filedialog.askdirectory(title="Selecciona la carpeta del proyecto")
        if path:
            self.project_var.set(path)

    def pick_output(self) -> None:
        proj = self.project_var.get().strip()
        base = os.path.basename(os.path.normpath(proj)) or "proyecto"
        default_name = f"{base}_sources.txt"
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
        is_dirlike = meta.kind in {"root-extras", "root-srcroot", "dir", "extra-group"}
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
        for root in list(self.src_roots_nodes.values()) + [self.extras_root]:
            self.set_state_recursive(root, on)

    def expand_collapse_all(self, expand: bool) -> None:
        def _walk(it: str) -> None:
            self.tree.item(it, open=expand)
            for ch in self.tree.get_children(it):
                _walk(ch)
        for root in list(self.src_roots_nodes.values()) + [self.extras_root]:
            _walk(root)

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

    def parse_roots(self) -> List[str]:
        raw = self.roots_var.get().strip()
        if not raw:
            return ["lib"]
        return [r.strip().strip("\\/") for r in raw.split(",") if r.strip()]

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
        if group not in self.src_root_files_nodes:
            self.src_root_files_nodes[group] = {}
        self.src_root_files_nodes[group][os.path.normcase(os.path.abspath(path))] = node
        return node

    def _prepare_srcroot(self, project_root: str, root_name: str) -> Optional[str]:
        root_path = os.path.join(project_root, root_name)
        if not os.path.isdir(root_path):
            return None
        # crea root en árbol
        root_item = self.tree.insert("", "end", text=f"{root_name} (sin escanear)", open=True)
        self.item_meta[root_item] = NodeMeta("root-srcroot", root_path, root_path, root_name, root_name, selectable=True)
        self.item_state[root_item] = 1
        self.src_roots_nodes[root_name] = root_item
        return root_item

    def scan_project(self) -> None:
        # limpiar raíces previas
        for node in list(self.src_roots_nodes.values()):
            try:
                self.tree.delete(node)
            except Exception:
                pass
        self.src_roots_nodes.clear()
        self.src_root_files_nodes.clear()

        project_root = self.project_var.get().strip()
        if not project_root or not os.path.isdir(project_root):
            messagebox.showerror("Error", "Selecciona una ruta de proyecto válida.")
            return

        allowed_exts = self.parse_exts()
        excludes = self.parse_excludes()
        roots = self.parse_roots()

        for root_name in roots:
            root_item = self._prepare_srcroot(project_root, root_name)
            if not root_item:
                continue
            root_path = os.path.join(project_root, root_name)
            self.tree.item(root_item, text=root_name)

            # Limpieza por si re-escaneo
            self.clear_children(root_item)

            entries = os.listdir(root_path)
            # archivos top
            top_files = [e for e in entries if os.path.isfile(os.path.join(root_path, e))]
            for f in sorted_casefold(top_files):
                ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                if ext in allowed_exts:
                    self.add_file_node(root_item, f, os.path.join(root_path, f), root_path, root_name, default_on=True)

            # subcarpetas
            top_dirs = [e for e in entries if os.path.isdir(os.path.join(root_path, e))]
            for d in sorted_casefold(top_dirs):
                if d in excludes:
                    continue
                dir_path = os.path.join(root_path, d)
                node = self.add_dir_node(root_item, d, dir_path, root_path, root_name)
                self.populate_dir(node, dir_path, root_path, allowed_exts, excludes, root_name)

            self.tree.item(root_item, open=True)

        # EXTRAS por defecto la primera vez
        if not self.extras_loaded_once:
            self.ensure_default_extras(project_root)
            self.extras_loaded_once = True

        self.tree.item(self.extras_root, open=True)

    def populate_dir(self, parent: str, dir_path: str, root_path: str,
                     allowed_exts: Set[str], excludes: Set[str], group_name: str) -> None:
        try:
            entries = os.listdir(dir_path)
        except PermissionError:
            return

        files = [e for e in entries if os.path.isfile(os.path.join(dir_path, e))]
        for f in sorted_casefold(files):
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in allowed_exts:
                self.add_file_node(parent, f, os.path.join(dir_path, f), root_path, group_name, default_on=True)

        dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
        for d in sorted_casefold(dirs):
            if d in excludes:
                continue
            dpath = os.path.join(dir_path, d)
            node = self.add_dir_node(parent, d, dpath, root_path, group_name)
            self.populate_dir(node, dpath, root_path, allowed_exts, excludes, group_name)

        self.recompute_parent_states(parent)

    # ------------------- EXTRAS -------------------

    def ensure_default_extras(self, project_root: str) -> None:
        self.clear_children(self.extras_root)
        self.extras_file_nodes.clear()
        label = "pubspec"
        group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label}]", open=True)
        self.item_meta[group_node] = NodeMeta("extra-group", "", project_root, "extras-group", f"[{label}]", selectable=True)
        self.item_state[group_node] = 1
        path = os.path.join(project_root, "pubspec.yaml")
        lbl = os.path.relpath(path, project_root).replace(os.sep, "/")
        self.add_file_node(group_node, lbl, os.path.abspath(path), project_root, "extras", default_on=True)
        self.recompute_parent_states(self.extras_root)

    def add_extra_file(self) -> None:
        proj = self.project_var.get().strip()
        initial = proj if os.path.isdir(proj) else os.getcwd()
        path = filedialog.askopenfilename(title="Elegir archivo EXTRA", initialdir=initial)
        if not path:
            return
        label_group = simpledialog.askstring("Etiqueta", "Etiqueta (opcional):", parent=self) or os.path.basename(path)
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
        exts = simpledialog.askstring("Extensiones", "Filtrar por extensiones (coma). Enter=Todas:", parent=self)
        allowed = {e.strip().lower().lstrip(".") for e in exts.split(",")} if exts else None

        dlg = SelectFromFolderDialog(self, base, allowed)
        selected = dlg.show()
        if not selected:
            return

        label_group = simpledialog.askstring("Etiqueta", "Etiqueta (opcional):", parent=self) or os.path.basename(base)

        group_node = self.tree.insert(self.extras_root, "end", text=f"{CHECK_ON} [{label_group}]", open=True)
        self.item_meta[group_node] = NodeMeta("extra-group", "", proj, "extras-group", f"[{label_group}]", selectable=True)
        self.item_state[group_node] = 1

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
            self.add_file_node(cur_parent, parts[-1], abs_path, proj, "extras", default_on=True)

        self.recompute_parent_states(self.extras_root)

    def add_extra_glob(self) -> None:
        proj = self.project_var.get().strip()
        patt = simpledialog.askstring("Patrón glob", "Patrón relativo (ej: test/**/*.dart):", parent=self)
        if not patt:
            return
        label_group = simpledialog.askstring("Etiqueta", "Etiqueta (opcional):", parent=self) or patt
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
        parent_chain: List[str] = []
        cur: Optional[str] = item
        while cur:
            parent_chain.append(cur)
            cur = self.tree.parent(cur)
        if self.extras_root not in parent_chain or item == self.extras_root:
            messagebox.showwarning("Aviso", "Solo puedes eliminar elementos dentro de EXTRAS.")
            return
        self.tree.delete(item)

    # ----------------- Recolección / escritura -----------------

    def _gather_files_selected_by_root(self, root_item: str) -> List[Tuple[str, str, bool]]:
        """Lista (abs_path, root_rel, is_selected) siguiendo el árbol."""
        result: List[Tuple[str, str, bool]] = []
        def walk(it: str) -> None:
            state = self.item_state.get(it, 0)
            meta = self.item_meta.get(it)
            if not meta:
                return
            if meta.kind == "file":
                result.append((os.path.abspath(meta.path), meta.root_for_rel, state == 1))
            for ch in self.tree.get_children(it):
                walk(ch)
        walk(root_item)
        return result

    def _gather_all_src_roots(self) -> List[Tuple[str, str]]:
        """Retorna pares (root_name, root_path_itemid)."""
        return [(name, item_id) for name, item_id in self.src_roots_nodes.items()]

    def _separator_line(self, text: str, is_end: bool) -> str:
        ch = (self.sep_char_var.get() or "-")[0]
        if self.sep_auto_var.get():
            base = f"{'END ' if is_end else ''}FILE: {text}"
            width = min(max(len(base) + 8, 60), 120)
        else:
            width = max(20, int(self.sep_width_var.get()))
        label = f" {'END ' if is_end else ''}FILE: {text} "
        line = (ch * width)
        mid = width // 2
        start = max(0, mid - len(label)//2)
        end = start + len(label)
        return f"{line[:start]}{label}{line[end:]}\n"

    def _write_file_block(self, out_fh: TextIO, file_abs_path: str, root_for_rel: str,
                          filename_only: bool) -> int:
        rel = os.path.relpath(file_abs_path, root_for_rel).replace(os.sep, "/")
        header = os.path.basename(rel) if filename_only else rel
        out_fh.write(self._separator_line(header, is_end=False))
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
        if self.sep_end_var.get():
            out_fh.write("\n")
            out_fh.write(self._separator_line(header, is_end=True))
        out_fh.write("\n")
        return written

    def generate_txt(self) -> None:
        project_root = self.project_var.get().strip()
        if not project_root or not os.path.isdir(project_root):
            messagebox.showerror("Error", "Selecciona una ruta de proyecto válida.")
            return

        out_path = self.out_var.get().strip()
        if not out_path:
            base = os.path.basename(os.path.normpath(project_root)) or "proyecto"
            out_path = os.path.join(os.getcwd(), f"{base}_sources.txt")

        filename_only = self.filename_only_var.get()
        verbose = self.verbose_var.get()
        excludes = self.parse_excludes()
        allowed_exts = self.parse_exts()
        mode = self.output_mode_var.get()
        include_all_structure = (mode != "content_selected")

        if verbose:
            print("—" * 90)
            print("Generando archivo…")
            print(f"Salida: {out_path}")
            print(f"Modo: {mode}")
            print(f"Raíces: {', '.join(self.parse_roots())}")

        try:
            with open(out_path, "w", encoding="utf-8") as out_fh:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                out_fh.write(f"GENERADO: {now}\n")
                out_fh.write(f"PROYECTO: {project_root}\n")
                out_fh.write(f"RAICES: {self.roots_var.get().strip()}\n")
                out_fh.write("=" * 80 + "\n\n")

                # ============ EXTRAS ============
                extras_all = self._gather_files_selected_by_root(self.extras_root)
                if extras_all:
                    out_fh.write("EXTRAS (inicio)\n")
                    out_fh.write("=" * 80 + "\n\n")
                    for abs_path, root_for_rel, is_selected in extras_all:
                        rel = os.path.relpath(abs_path, root_for_rel).replace(os.sep, "/")
                        header = os.path.basename(rel) if filename_only else rel
                        if mode == "structure_only":
                            out_fh.write(self._separator_line(header, is_end=False))
                            if self.sep_end_var.get():
                                out_fh.write(self._separator_line(header, is_end=True))
                            out_fh.write("\n")
                        elif mode == "selected_plus_structure":
                            if is_selected:
                                self._write_file_block(out_fh, abs_path, root_for_rel, filename_only)
                            else:
                                out_fh.write(self._separator_line(header, is_end=False))
                                if self.sep_end_var.get():
                                    out_fh.write(self._separator_line(header, is_end=True))
                                out_fh.write("\n")
                        else:  # content_selected
                            if is_selected:
                                self._write_file_block(out_fh, abs_path, root_for_rel, filename_only)
                    out_fh.write("\n")

                # ============ POR CADA RAÍZ ============
                def subtree_has_any_allowed(path: str) -> bool:
                    try:
                        entries = os.listdir(path)
                    except PermissionError:
                        return False
                    for f in entries:
                        p = os.path.join(path, f)
                        if os.path.isfile(p):
                            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                            if ext in allowed_exts:
                                return True
                    for d in entries:
                        p = os.path.join(path, d)
                        if os.path.isdir(p) and os.path.basename(p) not in excludes:
                            if subtree_has_any_allowed(p):
                                return True
                    return False

                def write_descend(cur: str, root_path: str, sel_set: Set[str]) -> None:
                    try:
                        entries = os.listdir(cur)
                    except PermissionError:
                        return
                    files = [e for e in entries if os.path.isfile(os.path.join(cur, e))]
                    for f in sorted_casefold(files):
                        fpath = os.path.join(cur, f)
                        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                        if ext not in allowed_exts:
                            continue
                        absn = os.path.normcase(os.path.abspath(fpath))
                        rel = os.path.relpath(fpath, root_path).replace(os.sep, "/")
                        header = os.path.basename(rel) if filename_only else rel

                        if mode == "content_selected":
                            if absn in sel_set:
                                self._write_file_block(out_fh, fpath, root_path, filename_only)
                        elif mode == "structure_only":
                            out_fh.write(self._separator_line(header, is_end=False))
                            if self.sep_end_var.get():
                                out_fh.write(self._separator_line(header, is_end=True))
                            out_fh.write("\n")
                        else:  # selected_plus_structure
                            if absn in sel_set:
                                self._write_file_block(out_fh, fpath, root_path, filename_only)
                            else:
                                out_fh.write(self._separator_line(header, is_end=False))
                                if self.sep_end_var.get():
                                    out_fh.write(self._separator_line(header, is_end=True))
                                out_fh.write("\n")

                    dirs = [e for e in entries if os.path.isdir(os.path.join(cur, e))]
                    for subd in sorted_casefold(dirs):
                        if subd in excludes:
                            continue
                        subpath = os.path.join(cur, subd)
                        if include_all_structure:
                            if not subtree_has_any_allowed(subpath):
                                continue
                        else:
                            # si sólo contenido, imprime directorios solo si hay seleccionados dentro
                            if not any(os.path.normcase(os.path.abspath(os.path.join(dp, fn))) in sel_set
                                       for dp, _, fns in os.walk(subpath) for fn in fns):
                                continue
                        out_fh.write(dir_header(1, subd))
                        out_fh.write("\n")
                        write_descend(subpath, root_path, sel_set)

                for root_name, root_item in self._gather_all_src_roots():
                    root_path = os.path.join(project_root, root_name)
                    if not os.path.isdir(root_path):
                        continue
                    # Set seleccionados para esta raíz
                    sel_list = [(p, r) for (p, r, sel) in self._gather_files_selected_by_root(root_item) if sel]
                    sel_set: Set[str] = {os.path.normcase(os.path.abspath(p)) for (p, _) in sel_list}

                    out_fh.write(f"=== RAIZ: {root_name} ===\n\n")

                    # top-level files
                    top_entries = os.listdir(root_path)
                    top_files = [e for e in top_entries if os.path.isfile(os.path.join(root_path, e))]
                    for f in sorted_casefold(top_files):
                        fpath = os.path.join(root_path, f)
                        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                        if ext not in allowed_exts:
                            continue
                        absn = os.path.normcase(os.path.abspath(fpath))
                        rel = os.path.relpath(fpath, root_path).replace(os.sep, "/")
                        header = os.path.basename(rel) if filename_only else rel

                        if mode == "content_selected":
                            if absn in sel_set:
                                self._write_file_block(out_fh, fpath, root_path, filename_only)
                        elif mode == "structure_only":
                            out_fh.write(self._separator_line(header, is_end=False))
                            if self.sep_end_var.get():
                                out_fh.write(self._separator_line(header, is_end=True))
                            out_fh.write("\n")
                        else:
                            if absn in sel_set:
                                self._write_file_block(out_fh, fpath, root_path, filename_only)
                            else:
                                out_fh.write(self._separator_line(header, is_end=False))
                                if self.sep_end_var.get():
                                    out_fh.write(self._separator_line(header, is_end=True))
                                out_fh.write("\n")

                    # subcarpetas con encabezados
                    top_dirs = [e for e in top_entries if os.path.isdir(os.path.join(root_path, e))]
                    for d in sorted_casefold(top_dirs):
                        if d in excludes:
                            continue
                        dpath = os.path.join(root_path, d)
                        if include_all_structure:
                            if not subtree_has_any_allowed(dpath):
                                continue
                        else:
                            # imprime dir solo si hay seleccionados adentro
                            if not any(os.path.normcase(os.path.abspath(os.path.join(dp, fn))) in sel_set
                                       for dp, _, fns in os.walk(dpath) for fn in fns):
                                continue
                        out_fh.write(dir_header(1, d))
                        out_fh.write("\n")
                        write_descend(dpath, root_path, sel_set)

            if verbose:
                print("✅ TXT generado correctamente.")
            messagebox.showinfo("Listo", f"Archivo generado:\n{out_path}")

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el TXT:\n{e}")
            if verbose:
                raise

    # ------------------- Perfiles -------------------

    def build_profile_payload(self) -> Dict[str, Any]:
        """Empaqueta opciones + selección actual (todas las raíces + extras)."""
        proj = os.path.abspath(self.project_var.get().strip())

        # Recoger seleccionados por cada raíz
        lib_selected_rel: List[str] = []
        for _, root_item in self._gather_all_src_roots():  # _ evita warning "unused variable"
            for abs_path, _ in [(p, r) for (p, r, sel) in self._gather_files_selected_by_root(root_item) if sel]:
                lib_selected_rel.append(os.path.relpath(abs_path, proj).replace(os.sep, "/"))

        # Extras agrupados
        extras_by_group: Dict[str, List[str]] = {}
        def walk(it: str, current_group: Optional[str]) -> None:
            meta = self.item_meta[it]
            base_group = current_group
            if meta.kind == "extra-group":
                base_group = meta.label.strip()
                if base_group.startswith("[") and base_group.endswith("]"):
                    base_group = base_group[1:-1]
            if meta.kind == "file" and self.item_state[it] == 1 and meta.group == "extras":
                rel = os.path.relpath(meta.path, proj).replace(os.sep, "/")
                extras_by_group.setdefault(base_group or "Extras", []).append(rel)
            for ch in self.tree.get_children(it):
                walk(ch, base_group)
        for ch in self.tree.get_children(self.extras_root):
            walk(ch, None)

        return {
            "project_root": proj,
            "options": {
                "source_roots": self.roots_var.get().strip(),
                "extensions": self.ext_var.get().strip(),
                "excludes": self.exclude_var.get().strip(),
                "filename_only": self.filename_only_var.get(),
                "verbose": self.verbose_var.get(),
                "output_mode": self.output_mode_var.get(),
                "sep_char": (self.sep_char_var.get() or "-")[0],
                "sep_width": int(self.sep_width_var.get()),
                "sep_auto": self.sep_auto_var.get(),
                "sep_print_end": self.sep_end_var.get(),
            },
            "selected_files_rel": sorted(set(lib_selected_rel), key=str.casefold),
            "extras_groups": [{"label": lbl, "files": files} for lbl, files in extras_by_group.items()],
        }

    def apply_profile_payload(self, payload: Dict[str, Any]) -> None:
        """Aplica un perfil (reemplaza selección)."""
        proj = str(payload.get("project_root") or self.project_var.get())
        self.project_var.set(proj)
        opts: Dict[str, Any] = dict(payload.get("options", {}))
        self.roots_var.set(str(opts.get("source_roots", self.roots_var.get())))
        self.ext_var.set(str(opts.get("extensions", self.ext_var.get())))
        self.exclude_var.set(str(opts.get("excludes", self.exclude_var.get())))
        self.filename_only_var.set(bool(opts.get("filename_only", self.filename_only_var.get())))
        self.verbose_var.set(bool(opts.get("verbose", self.verbose_var.get())))
        self.output_mode_var.set(str(opts.get("output_mode", self.output_mode_var.get())))
        self.sep_char_var.set(str(opts.get("sep_char", self.sep_char_var.get()))[:1] or "-")
        self.sep_width_var.set(int(opts.get("sep_width", self.sep_width_var.get())))
        self.sep_auto_var.set(bool(opts.get("sep_auto", self.sep_auto_var.get())))
        self.sep_end_var.set(bool(opts.get("sep_print_end", self.sep_end_var.get())))

        # escanear con nuevas raíces
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
                if os.path.isfile(abs_path):
                    self.add_file_node(cur_parent, parts[-1], abs_path, proj, "extras", default_on=True)
                else:
                    missing = self.add_file_node(cur_parent, parts[-1] + " [NO ENCONTRADO]", abs_path, proj, "extras", default_on=False)
                    self.item_meta[missing].selectable = False

        self.recompute_parent_states(self.extras_root)

        # deseleccionar todo en raíces
        for root_item in self.src_roots_nodes.values():
            for it in self.tree.get_children(root_item):
                self.set_state_recursive(it, False)

        # seleccionar según perfil
        proj_abs = os.path.abspath(proj)
        for rel in list(payload.get("selected_files_rel", [])):
            rel = str(rel)
            absn = os.path.normcase(os.path.abspath(os.path.join(proj_abs, rel)))
            # Busca en todas las raíces
            for group_map in self.src_root_files_nodes.values():
                node = group_map.get(absn)
                if node:
                    self.item_state[node] = 1
                    self.set_item_text(node, self.item_meta[node].label, 1)
                    self.recompute_parent_states(node)

    # ---- Acciones de perfiles (UI) ----

    def save_profile_dialog(self) -> None:
        store = _load_profile_store()
        name = simpledialog.askstring("Guardar perfil", "Nombre del perfil:", parent=self)
        if not name:
            return
        payload: Dict[str, Any] = self.build_profile_payload()
        store[name] = payload
        _save_profile_store(store)
        self.active_profiles = [name]
        self._refresh_profile_ui()
        messagebox.showinfo("Perfiles", f"Perfil '{name}' guardado.")

    def load_profile_dialog(self) -> None:
        store = _load_profile_store()
        if not store:
            messagebox.showinfo("Perfiles", "No hay perfiles guardados.")
            return
        names = sorted(store.keys(), key=str.casefold)
        sel = self._list_dialog("Cargar perfil", names, multi=False)
        if not sel:
            return
        name = sel[0]
        self.apply_profile_payload(store[name])
        self.active_profiles = [name]
        self._refresh_profile_ui()
        messagebox.showinfo("Perfiles", f"Perfil '{name}' cargado.")

    def delete_profile_dialog(self) -> None:
        store = _load_profile_store()
        if not store:
            messagebox.showinfo("Perfiles", "No hay perfiles guardados.")
            return
        names = sorted(store.keys(), key=str.casefold)
        sel = self._list_dialog("Borrar perfiles", names, multi=True)
        if not sel:
            return
        for name in sel:
            store.pop(name, None)
        _save_profile_store(store)
        self.active_profiles = [n for n in self.active_profiles if n in store]
        self._refresh_profile_ui()
        messagebox.showinfo("Perfiles", f"Borrados: {', '.join(sel)}")

    def activate_profiles_dialog(self) -> None:
        """Activa varios perfiles a la vez (fusión por unión)."""
        store = _load_profile_store()
        if not store:
            messagebox.showinfo("Perfiles", "No hay perfiles guardados.")
            return
        names = sorted(store.keys(), key=str.casefold)
        sel = self._list_dialog("Activar perfiles (múltiples)", names, multi=True)
        if not sel:
            return
        union_payload = self._build_union_payload([store[n] for n in sel])
        self.apply_profile_payload(union_payload)
        self.active_profiles = sel
        self._refresh_profile_ui()
        messagebox.showinfo("Perfiles", f"Perfiles activados: {', '.join(sel)}")

    def _build_union_payload(self, payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Une varias selecciones en una sola (∪). Mantiene opciones del primero."""
        if not payloads:
            return self.build_profile_payload()
        first = payloads[0]
        proj = first.get("project_root", self.project_var.get())
        options = dict(first.get("options", {}))

        sel_set: Set[str] = set()
        extras_map: Dict[str, Set[str]] = {}
        for p in payloads:
            for rel in p.get("selected_files_rel", []):
                sel_set.add(str(rel))
            for g in p.get("extras_groups", []):
                label = str(g.get("label") or "Extras")
                files = {str(r) for r in g.get("files", [])}
                extras_map.setdefault(label, set()).update(files)

        return {
            "project_root": proj,
            "options": options,
            "selected_files_rel": sorted(sel_set, key=str.casefold),
            "extras_groups": [{"label": lbl, "files": sorted(list(files), key=str.casefold)}
                              for lbl, files in extras_map.items()],
        }

    def _list_dialog(self, title: str, items: List[str], multi: bool) -> Optional[List[str]]:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.geometry("360x420")
        try:
            dlg.transient(self)  # type: ignore[arg-type]
        except Exception:
            pass
        dlg.grab_set()

        lb: tk.Listbox = tk.Listbox(dlg, selectmode=tk.EXTENDED if multi else tk.SINGLE)
        for it in items:
            lb.insert(tk.END, it)
        lb.pack(fill="both", expand=True, padx=8, pady=8)

        sel: List[str] = []

        def accept() -> None:
            indices_any: Any = cast(Any, lb).curselection()
            sel_idx: Tuple[int, ...] = tuple(int(x) for x in indices_any)
            chosen: List[str] = [items[i] for i in sel_idx]
            nonlocal sel
            sel = chosen
            dlg.destroy()

        def cancel() -> None:
            dlg.destroy()

        btns = ttk.Frame(dlg, padding=8)
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancelar", command=cancel).pack(side="right", padx=4)
        ttk.Button(btns, text="Aceptar", command=accept).pack(side="right", padx=4)

        dlg.bind("<Return>", lambda e: accept())
        dlg.bind("<Escape>", lambda e: cancel())

        dlg.wait_window(dlg)
        return sel or None

    # ------------------- Preferencias -------------------

    def save_prefs(self) -> None:
        prefs: Prefs = {
            "project_root": self.project_var.get().strip(),
            "source_roots": self.roots_var.get().strip(),
            "extensions": self.ext_var.get().strip(),
            "excludes": self.exclude_var.get().strip(),
            "filename_only": self.filename_only_var.get(),
            "verbose": self.verbose_var.get(),
            "output_mode": self.output_mode_var.get(),
            "sep_char": (self.sep_char_var.get() or "-")[0],
            "sep_width": int(self.sep_width_var.get()),
            "sep_auto": self.sep_auto_var.get(),
            "sep_print_end": self.sep_end_var.get(),
        }
        _save_prefs(prefs)
        messagebox.showinfo("Preferencias", "Preferencias guardadas.")

    def restore_prefs(self) -> None:
        prefs: Prefs = _load_prefs()
        if not prefs:
            messagebox.showinfo("Preferencias", "No hay preferencias guardadas.")
            return
        self.project_var.set(prefs.get("project_root", self.project_var.get()))
        self.roots_var.set(prefs.get("source_roots", self.roots_var.get()))
        self.ext_var.set(prefs.get("extensions", self.ext_var.get()))
        self.exclude_var.set(prefs.get("excludes", self.exclude_var.get()))
        self.filename_only_var.set(bool(prefs.get("filename_only", self.filename_only_var.get())))
        self.verbose_var.set(bool(prefs.get("verbose", self.verbose_var.get())))
        self.output_mode_var.set(prefs.get("output_mode", self.output_mode_var.get()))
        self.sep_char_var.set(str(prefs.get("sep_char", self.sep_char_var.get()))[:1] or "-")
        self.sep_width_var.set(int(prefs.get("sep_width", self.sep_width_var.get())))
        self.sep_auto_var.set(bool(prefs.get("sep_auto", self.sep_auto_var.get())))
        self.sep_end_var.set(bool(prefs.get("sep_print_end", self.sep_end_var.get())))
        messagebox.showinfo("Preferencias", "Preferencias restauradas.")

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
