import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { $el } from "../../scripts/ui.js";

function formatTitle(text) {
    return `🚀 ${text}`;
}

// Show save workflow dialog using ComfyUI native dialog
async function showSaveWorkflowDialog() {
    return new Promise((resolve) => {
        const html = '<h3 style="margin: 0 0 15px 0; color: var(--content-fg);">Save API Workflow</h3>' +
            '<div style="margin-bottom: 15px;">' +
            '<label style="display: block; margin-bottom: 5px; color: var(--content-fg);">Workflow name:</label>' +
            '<input type="text" id="workflow-name" placeholder="Enter workflow name" style="width: 100%; padding: 8px; box-sizing: border-box;" required>' +
            '</div>' +
            '<div>' +
            '<label style="display: flex; align-items: center; color: var(--content-fg);">' +
            '<input type="checkbox" id="overwrite-checkbox" style="margin-right: 8px;">' +
            'Overwrite if exists' +
            '</label>' +
            '</div>';
        
        // Use existing dialog instance
        const dialog = app.ui.dialog;
        
        // Show the dialog with HTML content
        dialog.show(html);
        
        // Replace the default buttons with our custom buttons
        const modalContent = dialog.element.querySelector('.comfy-modal-content');
        const defaultButtons = modalContent.querySelectorAll('button');
        defaultButtons.forEach(btn => btn.remove());
        
        // Handle cancel
        const handleCancel = () => {
            dialog.close();
            resolve(null);
        };
        
        // Handle save
        const handleSave = () => {
            const nameInput = dialog.element.querySelector('#workflow-name');
            const overwriteCheckbox = dialog.element.querySelector('#overwrite-checkbox');
            const name = nameInput.value.trim();
            if (!name) {
                alert('Please enter a workflow name');
                nameInput.focus();
                return;
            }
            
            dialog.close();
            resolve({
                name: name,
                overwrite: overwriteCheckbox.checked
            });
        };
        
        // Create our custom button container using $el
        const buttonContainer = $el('div', {
            style: {
                display: 'flex',
                gap: '10px',
                justifyContent: 'flex-end'
            }
        }, [
            $el('button', {
                textContent: 'Cancel',
                style: { padding: '8px 16px' },
                onclick: handleCancel
            }),
            $el('button', {
                textContent: 'Save',
                style: { padding: '8px 16px' },
                onclick: handleSave
            })
        ]);
        
        modalContent.appendChild(buttonContainer);
        
        // Get elements from the dialog
        const nameInput = dialog.element.querySelector('#workflow-name');
        
        // Focus on name input
        setTimeout(() => nameInput?.focus(), 100);
        
        // Handle Enter key in name input
        nameInput?.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleSave();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                handleCancel();
            }
        });
    });
}

// Call save API
async function saveWorkflowApi(name, workflow, overwrite) {
    const response = await api.fetchApi('/oneapi/v1/save-api-workflow', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            name: name,
            workflow: workflow,
            overwrite: overwrite
        })
    });
    
    const responseData = await response.json();
    return { response, responseData };
}

// Show result message using ComfyUI native dialog
function showResultMessage(success, message) {
    const title = success ? 'Save Successful' : 'Save Failed';
    const color = success ? '#28a745' : '#dc3545';
    const html = '<h3 style="margin: 0 0 15px 0; color: ' + color + '; text-align: center;">' + title + '</h3>' +
        '<p style="margin: 0; text-align: center; color: var(--content-fg);">' + message + '</p>';
    
    const dialog = app.ui.dialog;
    
    // Show the dialog
    dialog.show(html);
    
    // Replace the default buttons with our custom button
    const modalContent = dialog.element.querySelector('.comfy-modal-content');
    const defaultButtons = modalContent.querySelectorAll('button');
    defaultButtons.forEach(btn => btn.remove());
    
    // Create our custom button container using $el
    const buttonContainer = $el('div', {
        style: {
            display: 'flex',
            justifyContent: 'center'
        }
    }, [
        $el('button', {
            textContent: 'OK',
            style: { padding: '8px 16px' },
            onclick: () => dialog.close(),
            $: (btn) => setTimeout(() => btn.focus(), 100)
        })
    ]);
    
    modalContent.appendChild(buttonContainer);
}

// Main function to save workflow as API
async function saveWorkflowAsAPI() {
    try {
        // Get workflow data
        const result = await app.graphToPrompt();
        const workflow = result.output;
        
        // Show save dialog
        const formValues = await showSaveWorkflowDialog();
        if (!formValues) return;
        
        const { name, overwrite } = formValues;
        
        // Call save API
        const { response, responseData } = await saveWorkflowApi(name, workflow, overwrite);
        
        // Show result
        if (response.ok) {
            showResultMessage(true, `Workflow saved as: ${responseData.filename}`);
        } else {
            showResultMessage(false, responseData.error || 'Unknown error');
        }
    } catch (error) {
        console.error('Error saving workflow:', error);
        showResultMessage(false, 'Error occurred while saving workflow: ' + error.message);
    }
}

function addCanvasMenuOptions() {
    const original_getCanvasMenuOptions = LGraphCanvas.prototype.getCanvasMenuOptions;
    LGraphCanvas.prototype.getCanvasMenuOptions = function () {
        // get the basic options 
        const originOptions = original_getCanvasMenuOptions.apply(this, arguments);
        
        const addedOptions = [
            {
                content: formatTitle("Save Workflow as API"),
                callback: saveWorkflowAsAPI
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
                content: formatTitle("Set Node Input"),
                callback: async () => {
                    const selectedNodes = app.canvas.selected_nodes;
                    const selectedNodeIds = Object.keys(selectedNodes);
                    if (selectedNodeIds.length > 1) {
                        alert('Please select only one node');
                        return;
                    }

                    const nodeId = selectedNodeIds[0];
                    const node = selectedNodes[nodeId];
                    const fieldNames = node.widgets.map(e => e.name);
                    
                    // Show field selection dialog
                    const fieldName = await showFieldSelectionDialog(fieldNames);
                    if (!fieldName) return;
                    
                    // Show variable name input dialog
                    const varName = await showVariableNameDialog(fieldName);
                    if (!varName) return;
                    
                    addVar2Node(node, varName, fieldName);
                }
            })
        }
}

// Show field selection dialog
async function showFieldSelectionDialog(fieldNames) {
    return new Promise((resolve) => {
        const options = fieldNames.map((name, index) => 
            '<div style="margin-bottom: 8px;">' +
            '<label style="display: flex; align-items: center; color: var(--content-fg); cursor: pointer;">' +
            '<input type="radio" name="field-selection" value="' + name + '" style="margin-right: 8px;">' +
            name +
            '</label>' +
            '</div>'
        ).join('');
        
        const html = '<h3 style="margin: 0 0 15px 0; color: var(--content-fg);">Select Input Field</h3>' +
            '<div id="radio-container">' +
            options +
            '</div>';
        
        const dialog = app.ui.dialog;
        
        // Show the dialog
        dialog.show(html);
        
        // Replace the default buttons with our custom buttons
        const modalContent = dialog.element.querySelector('.comfy-modal-content');
        const defaultButtons = modalContent.querySelectorAll('button');
        defaultButtons.forEach(btn => btn.remove());
        
        const handleCancel = () => {
            dialog.close();
            resolve(null);
        };
        
        const handleOK = () => {
            const selectedRadio = dialog.element.querySelector('input[name="field-selection"]:checked');
            if (!selectedRadio) {
                alert('Please select a field');
                return;
            }
            dialog.close();
            resolve(selectedRadio.value);
        };
        
        // Create our custom button container using $el
        const buttonContainer = $el('div', {
            style: {
                display: 'flex',
                gap: '10px',
                justifyContent: 'flex-end'
            }
        }, [
            $el('button', {
                textContent: 'Cancel',
                style: { padding: '8px 16px' },
                onclick: handleCancel
            }),
            $el('button', {
                textContent: 'OK',
                style: { padding: '8px 16px' },
                onclick: handleOK
            })
        ]);
        
        modalContent.appendChild(buttonContainer);
        
        // Auto-select first option and focus on it
        setTimeout(() => {
            const firstRadio = dialog.element.querySelector('input[name="field-selection"]');
            if (firstRadio) {
                firstRadio.checked = true;
                firstRadio.focus();
            }
        }, 100);

        // 基于 radio 按钮父控件监听键盘事件
        const radioContainer = dialog.element.querySelector('#radio-container');
        radioContainer?.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleOK();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                handleCancel();
            }
        });
    });
}

// Show variable name input dialog
async function showVariableNameDialog(fieldName) {
    return new Promise((resolve) => {
        const html = '<h3 style="margin: 0 0 15px 0; color: var(--content-fg);">Set Variable Name for `' + fieldName + '`</h3>' +
            '<div>' +
            '<input type="text" id="var-name" placeholder="Enter variable name" style="width: 100%; padding: 8px; box-sizing: border-box;" required>' +
            '</div>';
        
        const dialog = app.ui.dialog;
        
        // Show the dialog
        dialog.show(html);
        
        // Replace the default buttons with our custom buttons
        const modalContent = dialog.element.querySelector('.comfy-modal-content');
        const defaultButtons = modalContent.querySelectorAll('button');
        defaultButtons.forEach(btn => btn.remove());
        
        const handleCancel = () => {
            dialog.close();
            resolve(null);
        };
        
        const handleOK = () => {
            const varNameInput = dialog.element.querySelector('#var-name');
            const varName = varNameInput.value.trim();
            if (!varName) {
                alert('Please enter a variable name');
                varNameInput?.focus();
                return;
            }
            dialog.close();
            resolve(varName);
        };
        
        // Create our custom button container using $el
        const buttonContainer = $el('div', {
            style: {
                display: 'flex',
                gap: '10px',
                justifyContent: 'flex-end'
            }
        }, [
            $el('button', {
                textContent: 'Cancel',
                style: { padding: '8px 16px' },
                onclick: handleCancel
            }),
            $el('button', {
                textContent: 'OK',
                style: { padding: '8px 16px' },
                onclick: handleOK
            })
        ]);
        
        modalContent.appendChild(buttonContainer);
        
        // Get elements
        const varNameInput = dialog.element.querySelector('#var-name');
        
        setTimeout(() => varNameInput?.focus(), 100);
        
        // 基于文本输入框监听键盘事件
        varNameInput?.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleOK();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                handleCancel();
            }
        });
    });
}

function addVar2Node(node, varName, fieldName) {
    const newPart = '$' + varName + '.' + fieldName;
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
        addCanvasMenuOptions();
    },
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // Custom node right-click menu
        addExtraMenuOptions(nodeType, nodeData, app);
    },
})
