import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const Swal = window.Sweetalert2;

function addCanvasMenuOptions() {
    const original_getCanvasMenuOptions = LGraphCanvas.prototype.getCanvasMenuOptions;
    LGraphCanvas.prototype.getCanvasMenuOptions = function () {
        // get the basic options 
        const originOptions = original_getCanvasMenuOptions.apply(this, arguments);
        
        const addedOptions = [
            {
                content: "T Load Default Workflow",
                callback: async () => {
                    Swal.fire({
                        title: 'Hello',
                        text: 'Hello',
                        icon: 'success',
                        confirmButtonText: 'OK'
                    });
                }
            },
            null
        ]
        return [...addedOptions, ...originOptions];
        // return originOptions;
    }
}

function addExtraMenuOptions(nodeType, nodeData, app) {
    const nodeTypeClass = nodeType?.comfyClass;
    const original_getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (_, options) {
            original_getExtraMenuOptions?.apply(this, arguments);
            options.splice(0, 0, {
                content: "Set Node Input",
                callback: async () => {
                    const selectedNodes = app.canvas.selected_nodes;
                    const selectedNodeIds = Object.keys(selectedNodes);
                    if (selectedNodeIds.length > 1) {
                        Swal.fire({
                            title: 'Error',
                            text: 'Please select only one node',
                            icon: 'error',
                            confirmButtonText: 'OK'
                        });
                        return;
                    }

                    const nodeId = selectedNodeIds[0];
                    const node = selectedNodes[nodeId];
                    const fieldNames = node.widgets.map(e => e.name);
                    const selectedFieldName = await Swal.fire({
                        title: 'Select Input Field',
                        input: 'select',
                        inputOptions: fieldNames,
                        inputPlaceholder: 'Select Input Field',
                        confirmButtonText: 'OK'
                    });
                    const fieldIndex = selectedFieldName.value;
                    if (fieldIndex !== "") {
                        const fieldName = fieldNames[fieldIndex];
                        const varName = await Swal.fire({
                            title: `Select Variable Name for ${fieldName}`,
                            input: 'text',
                            inputPlaceholder: 'Select Variable Name',
                            inputValidator: (value) => {
                                if (!value) {
                                    return 'Please enter a variable name';
                                }
                            },
                            confirmButtonText: 'OK'
                        });
                        addVar2Node(node, varName.value, fieldName);
                    }
                }
            })
        }
}

function addVar2Node(node, varName, fieldName) {
    const newPart = `$${varName}.${fieldName}`;
    // Split and remove existing items with the same fieldName
    let parts = node.title.split(',').map(item => item.trim());
    parts = parts.filter(item => {
        // Match $xxx.fieldName
        const match = item.match(/^\$[^.]+\.(.+)$/);
        // Keep items that are not the current fieldName, or not in $xxx.fieldName format
        return !(match && match[1] === fieldName);
    });
    // Add the new one
    parts.push(newPart);
    // Rejoin
    node.title = parts.filter(Boolean).join(',');
}

app.registerExtension({
    name: "ComfyUI-OneAPI-ConvertUIToAPI",
    async setup() {
        // Custom canvas background right-click menu
        // addCanvasMenuOptions();
    },
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // Custom node right-click menu
        addExtraMenuOptions(nodeType, nodeData, app);
    },
})
