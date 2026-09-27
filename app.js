"use strict";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const SUPPORTED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const DRAG_TYPE = "application/x-tierlist-photo";
const $ = (selector) => document.querySelector(selector);
const elements = {
    files: $("#files-input"), folder: $("#folder-input"), slot: $("#slot-input"),
    status: $("#save-status"), selection: $("#selection-status"), photos: $("#photos"),
    library: $("#library"), count: $("#photo-count"), empty: $("#empty-library"),
    clear: $("#clear-selection"), retry: $("#retry"),
    boardLinks: $("#board-links"), boardForm: $("#new-board-form"), boardName: $("#new-board-name"),
    deleteDialog: $("#delete-dialog"), deleteDescription: $("#delete-description"),
};
let images = [];
let boards = [];
let boardId = null;
let selectedId = null;
let slotToImport = null;
let busy = true;
let connected = false;
let pendingDeletion = null;

function setStatus(message, kind = "info") {
    elements.status.textContent = message;
    elements.status.dataset.kind = kind;
}

function updateControls() {
    document.querySelectorAll("button, input").forEach((button) => {
        if (button !== elements.retry) button.disabled = busy || !connected;
    });
    elements.retry.disabled = busy;
    $("main").setAttribute("aria-busy", String(busy));
}

async function api(path, options = {}) {
    let response;
    try {
        response = await fetch(path, {
            ...options, headers: { "Content-Type": "application/json", ...options.headers },
        });
    } catch {
        throw new Error("Não foi possível conectar ao servidor. Verifique se ele continua aberto e tente novamente.");
    }
    const result = await response.json().catch(() => null);
    if (!response.ok || !result) {
        throw new Error(result?.error || "O servidor não conseguiu concluir a operação. Tente novamente.");
    }
    return result;
}

function createPhoto(image) {
    const photo = document.createElement("img");
    photo.src = image.url;
    photo.alt = image.name;
    photo.draggable = false;
    photo.loading = "lazy";
    return photo;
}

function makeDraggable(button, image) {
    button.draggable = true;
    button.addEventListener("dragstart", (event) => {
        if (busy || !connected) { event.preventDefault(); return; }
        event.dataTransfer.setData(DRAG_TYPE, String(image.id));
        event.dataTransfer.effectAllowed = "move";
    });
    button.addEventListener("dragend", () => {
        document.querySelectorAll(".drop-target").forEach((target) => target.classList.remove("drop-target"));
    });
}

function selectImage(id) {
    selectedId = selectedId === id ? null : id;
    render();
}

function renderBoards() {
    elements.boardLinks.replaceChildren();
    for (const board of boards) {
        const item = document.createElement("div");
        item.className = "board-item";
        const link = document.createElement("a");
        link.href = `/?board=${board.id}`;
        link.textContent = board.name;
        if (board.id === boardId) link.setAttribute("aria-current", "page");
        item.append(link);
        if (board.id !== 1) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "delete-board";
            button.textContent = "🗑";
            button.title = `Excluir tier list ${board.name}`;
            button.setAttribute("aria-label", `Excluir tier list ${board.name}`);
            button.addEventListener("click", () => requestDeleteBoard(board));
            item.append(button);
        }
        elements.boardLinks.append(item);
    }
}

function makeDeleteButton(image) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "delete-photo";
    button.textContent = "🗑";
    button.title = "Excluir foto definitivamente";
    button.setAttribute("aria-label", `Excluir definitivamente ${image.name}`);
    button.addEventListener("click", () => deleteImage(image));
    return button;
}

function deleteImage(image) {
    if (busy || !connected) return;
    pendingDeletion = { type: "image", image };
    openDeleteDialog("Excluir foto?", `A foto “${image.name}” será apagada definitivamente desta tier list e do banco SQLite. Essa ação não pode ser desfeita.`, "Excluir foto");
}

function requestDeleteBoard(board) {
    if (busy || !connected || board.id === 1) return;
    pendingDeletion = { type: "board", board };
    openDeleteDialog("Excluir tier list?", `A tier list “${board.name}” e todas as fotos que pertencem a ela serão apagadas definitivamente. Essa ação não pode ser desfeita.`, "Excluir tier list");
}

function openDeleteDialog(title, description, confirmLabel) {
    $("#delete-title").textContent = title;
    elements.deleteDescription.textContent = description;
    $("#confirm-delete").textContent = confirmLabel;
    elements.deleteDialog.returnValue = "cancel";
    elements.deleteDialog.showModal();
    $("#cancel-delete").focus();
}

function acceptDrop(target, onPhoto, onFiles) {
    target.addEventListener("dragover", (event) => {
        if (busy || !connected) return;
        const types = Array.from(event.dataTransfer.types);
        if (!types.includes(DRAG_TYPE) && !types.includes("Files")) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = types.includes("Files") ? "copy" : "move";
        target.classList.add("drop-target");
    });
    target.addEventListener("dragleave", (event) => {
        if (!target.contains(event.relatedTarget)) target.classList.remove("drop-target");
    });
    target.addEventListener("drop", (event) => {
        event.preventDefault();
        event.stopPropagation();
        target.classList.remove("drop-target");
        if (busy || !connected) return;
        if (event.dataTransfer.files.length) {
            onFiles(Array.from(event.dataTransfer.files));
        } else {
            const id = Number(event.dataTransfer.getData(DRAG_TYPE));
            if (images.some((image) => image.id === id)) onPhoto(id);
        }
    });
}

function render() {
    const focusedKey = document.activeElement?.dataset.key;
    if (!images.some((image) => image.id === selectedId)) selectedId = null;
    document.querySelectorAll(".tier").forEach((row) => {
        const tier = row.dataset.tier;
        row.replaceChildren();
        for (let slot = 0; slot < 8; slot += 1) {
            const image = images.find((item) => item.tier === tier && item.slot === slot);
            const wrapper = document.createElement("div");
            wrapper.className = "slot";
            const button = document.createElement("button");
            button.type = "button";
            button.className = "escolha";
            button.dataset.key = `slot-${tier}-${slot}`;
            button.setAttribute("aria-label", `${tier}, caixa ${slot + 1}: ${image ? image.name : "adicionar foto"}`);
            if (image) {
                button.append(createPhoto(image));
                button.setAttribute("aria-pressed", String(image.id === selectedId));
                button.classList.toggle("selected", image.id === selectedId);
                makeDraggable(button, image);
            } else {
                const plus = document.createElement("span");
                plus.className = "plus";
                plus.textContent = "+";
                plus.setAttribute("aria-hidden", "true");
                const number = document.createElement("span");
                number.className = "slot-number";
                number.textContent = `FOTO ${slot + 1}`;
                button.append(plus, number);
            }
            button.addEventListener("click", () => {
                if (selectedId !== null && selectedId !== image?.id) {
                    moveImage(selectedId, tier, slot);
                } else if (image) {
                    selectImage(image.id);
                } else {
                    slotToImport = { tier, slot };
                    elements.slot.click();
                }
            });
            wrapper.append(button);
            if (image) {
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "remove-photo";
                remove.textContent = "×";
                remove.dataset.key = `remove-${tier}-${slot}`;
                remove.setAttribute("aria-label", `Devolver ${image.name} às fotos disponíveis`);
                remove.title = "Devolver às fotos disponíveis";
                remove.addEventListener("click", () => unplaceImage(image));
                wrapper.append(remove, makeDeleteButton(image));
            }
            acceptDrop(wrapper, (id) => moveImage(id, tier, slot), (files) => importFiles(files, { tier, slot }));
            row.append(wrapper);
        }
    });
    elements.photos.replaceChildren();
    const available = images.filter((image) => image.tier === null);
    for (const image of available) {
        const item = document.createElement("div");
        item.className = "photo-item";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "photo-card";
        button.dataset.key = `photo-${image.id}`;
        button.setAttribute("aria-label", `Selecionar ${image.name}`);
        button.setAttribute("aria-pressed", String(image.id === selectedId));
        button.classList.toggle("selected", image.id === selectedId);
        button.append(createPhoto(image));
        button.addEventListener("click", () => selectImage(image.id));
        makeDraggable(button, image);
        const name = document.createElement("span");
        name.className = "photo-name";
        name.textContent = image.name;
        name.title = image.name;
        item.append(button, name);
        item.append(makeDeleteButton(image));
        elements.photos.append(item);
    }
    elements.count.textContent = String(available.length);
    elements.empty.hidden = available.length > 0;
    elements.empty.textContent = images.length
        ? "Todas as fotos estão no ranking. Importe mais ou use × para devolver uma foto para cá."
        : "Importe suas fotos para começar a resenha.";
    const selected = images.find((image) => image.id === selectedId);
    elements.selection.textContent = selected
        ? `${selected.name} selecionada. Clique na caixa de destino; se estiver ocupada, as fotos trocam de lugar.` : "";
    elements.clear.hidden = !selected;
    renderBoards();
    updateControls();
    if (focusedKey) {
        Array.from(document.querySelectorAll("[data-key]"))
            .find((element) => element.dataset.key === focusedKey)?.focus({ preventScroll: true });
    }
}

async function saveChange(path, options, successMessage = "Tudo salvo neste computador") {
    if (busy || !connected) return;
    busy = true;
    updateControls();
    setStatus("Salvando…");
    try {
        images = (await api(path, options)).images;
        selectedId = null;
        setStatus(successMessage, "success");
    } catch (error) {
        setStatus(error.message, "error");
    } finally {
        busy = false;
        render();
    }
}

function moveImage(imageId, tier, slot) {
    return saveChange("/api/slots", { method: "PUT", body: JSON.stringify({ imageId, tier, slot, boardId }) });
}

function unplaceImage(image) {
    if (image.tier !== null) return saveChange(`/api/slots/${image.tier}/${image.slot}?boardId=${boardId}`, { method: "DELETE" });
}

function readBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(new Error(`Não foi possível ler ${file.name}.`));
        reader.readAsDataURL(file);
    });
}

async function importFiles(files, destination = null) {
    if (busy || !connected || !files.length) return;
    const supported = files.filter((file) => SUPPORTED_TYPES.has(file.type) || (!file.type && /\.(png|jpe?g|webp|gif)$/i.test(file.name)));
    const valid = supported.filter((file) => file.size > 0 && file.size <= MAX_FILE_SIZE);
    const skipped = files.length - valid.length;
    if (!valid.length) {
        setStatus("Nenhuma foto válida. Escolha PNG, JPG, WebP ou GIF de até 10 MB.", "error");
        return;
    }
    busy = true;
    updateControls();
    let imported = 0;
    let failure = "";
    try {
        for (const file of valid) {
            setStatus(`Importando foto ${imported + 1} de ${valid.length}…`);
            const data = await readBase64(file);
            const result = await api("/api/images", {
                method: "POST",
                body: JSON.stringify({ boardId, name: file.name, data, ...(imported === 0 && destination ? destination : {}) }),
            });
            // Preserve confirmed uploads even if a later file fails.
            if (result.image.tier !== null) {
                images = images.map((image) => image.tier === result.image.tier && image.slot === result.image.slot
                    ? { ...image, tier: null, slot: null } : image);
            }
            images.push(result.image);
            imported += 1;
        }
    } catch (error) {
        failure = error.message;
    } finally {
        busy = false;
        selectedId = null;
        render();
        const summary = `${imported} foto(s) importada(s) e salva(s).`;
        const ignored = skipped ? ` ${skipped} arquivo(s) ignorado(s): formato incompatível, vazio ou acima de 10 MB.` : "";
        setStatus(`${summary}${ignored}${failure ? ` ${failure}` : ""}`, failure || skipped ? "error" : "success");
    }
}

async function loadState() {
    busy = true;
    elements.retry.hidden = true;
    updateControls();
    if (location.protocol === "file:") {
        busy = false;
        setStatus("Abra o site por http://127.0.0.1:8006 após executar python server.py na pasta do projeto.", "error");
        render();
        return;
    }
    setStatus("Carregando suas fotos…");
    try {
        boards = (await api("/api/boards")).boards;
        const requested = Number(new URLSearchParams(location.search).get("board"));
        boardId = boards.some((board) => board.id === requested) ? requested : boards[0].id;
        if (boardId !== requested) history.replaceState(null, "", `/?board=${boardId}`);
        images = (await api(`/api/state?boardId=${boardId}`)).images;
        document.title = `${boards.find((board) => board.id === boardId).name} · Tier list resenhuda`;
        connected = true;
        setStatus("Tudo salvo neste computador", "success");
    } catch (error) {
        connected = false;
        elements.retry.hidden = false;
        setStatus(error.message, "error");
    } finally {
        busy = false;
        render();
    }
}

$("#import-files").addEventListener("click", () => elements.files.click());
$("#import-folder").addEventListener("click", () => elements.folder.click());
for (const input of [elements.files, elements.folder, elements.slot]) {
    input.addEventListener("change", () => {
        const files = Array.from(input.files);
        const destination = input === elements.slot ? slotToImport : null;
        input.value = "";
        slotToImport = null;
        importFiles(files, destination);
    });
}
elements.clear.addEventListener("click", () => { selectedId = null; render(); });
elements.retry.addEventListener("click", loadState);
elements.deleteDialog.addEventListener("close", () => {
    const deletion = pendingDeletion;
    pendingDeletion = null;
    if (elements.deleteDialog.returnValue !== "delete" || !deletion) return;
    if (deletion.type === "image") {
        const { image } = deletion;
        saveChange(`/api/images/${image.id}?boardId=${boardId}`, { method: "DELETE" }, "Foto excluída definitivamente.");
        return;
    }
    deleteBoard(deletion.board);
});

async function deleteBoard(board) {
    busy = true;
    updateControls();
    setStatus("Excluindo tier list e as fotos dela…");
    try {
        boards = (await api(`/api/boards/${board.id}`, { method: "DELETE" })).boards;
        if (board.id === boardId) {
            location.assign(`/?board=${boards[0].id}`);
            return;
        }
        setStatus("Tier list excluída definitivamente.", "success");
    } catch (error) {
        setStatus(error.message, "error");
    } finally {
        busy = false;
        render();
    }
}
elements.boardForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !connected) return;
    busy = true;
    updateControls();
    setStatus("Criando tier list…");
    try {
        const result = await api("/api/boards", {
            method: "POST", body: JSON.stringify({ name: elements.boardName.value }),
        });
        location.assign(`/?board=${result.board.id}`);
    } catch (error) {
        busy = false;
        updateControls();
        setStatus(error.message, "error");
    }
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !busy) { selectedId = null; render(); }
});
acceptDrop(elements.library, (id) => unplaceImage(images.find((image) => image.id === id)), (files) => importFiles(files));
// Avoid navigating away when a file misses a drop zone.
for (const type of ["dragover", "drop"]) {
    document.addEventListener(type, (event) => {
        if (Array.from(event.dataTransfer.types).includes("Files")) event.preventDefault();
    });
}
render();
loadState();
