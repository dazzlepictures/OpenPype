"""Host API required Work Files tool"""
import os
import nuke
from qtpy import QtWidgets
import shutil


def file_extensions():
    return [".nk"]


def has_unsaved_changes():
    return nuke.root().modified()


def save_file(filepath):
    path = filepath.replace("\\", "/")
    nuke.scriptSaveAs(path, overwrite=1)
    nuke.Root()["name"].setValue(path)
    nuke.Root()["project_directory"].setValue(os.path.dirname(path))
    nuke.Root().setModified(False)


def open_file(filepath):
    filepath = filepath.replace("\\", "/")

    # To remain in the same window, we have to clear the script and read
    # in the contents of the workfile.
    def read_script(nuke_script):
        nuke.scriptClear()
        if int(nuke.NUKE_VERSION_MAJOR) > 12:
            nuke.scriptReadFile(nuke_script)
        else:
            nuke.scriptOpen(nuke_script)
        nuke.Root()["name"].setValue(nuke_script)
        nuke.Root()["project_directory"].setValue(os.path.dirname(nuke_script))
        nuke.Root().setModified(False)

    read_script(filepath)
    headless = QtWidgets.QApplication.instance() is None
    if not headless:
        autosave = str(nuke.toNode("preferences")["AutoSaveName"].evaluate())
        autosave_prmpt = "Autosave detected.\nWould you like to load the autosave file?"       # noqa
        if os.path.isfile(autosave) and nuke.ask(autosave_prmpt):
            try:
                shutil.copy(autosave, filepath)
                read_script(filepath)
            except:
                nuke.message("Autosave file could not be copied!")
    return True


def current_file():
    current_file = nuke.root().name()

    # Unsaved current file
    if current_file == 'Root':
        return None

    return os.path.normpath(current_file).replace("\\", "/")


def work_root(session):

    work_dir = session["AVALON_WORKDIR"]
    scene_dir = session.get("AVALON_SCENEDIR")
    if scene_dir:
        path = os.path.join(work_dir, scene_dir)
    else:
        path = work_dir

    return os.path.normpath(path).replace("\\", "/")
