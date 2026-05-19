/**
 * Copyright (c) 2006-2024, JGraph Holdings Ltd
 * Copyright (c) 2006-2024, draw.io AG
 */
// Overrides of global vars need to be pre-loaded
window.DRAWIO_PUBLIC_BUILD = true;
window.EXPORT_URL = 'REPLACE_WITH_YOUR_IMAGE_SERVER';
window.PLANT_URL = 'REPLACE_WITH_YOUR_PLANTUML_SERVER';
window.DRAWIO_BASE_URL = null; // Replace with path to base of deployment, e.g. https://www.example.com/folder
window.DRAWIO_VIEWER_URL = null; // Replace your path to the viewer js, e.g. https://www.example.com/js/viewer.min.js
window.DRAWIO_LIGHTBOX_URL = null; // Replace with your lightbox URL, eg. https://www.example.com
window.DRAW_MATH_URL = 'math4/es5';
window.DRAWIO_CONFIG = null; // Replace with your custom draw.io configurations. For more details, https://www.drawio.com/doc/faq/configure-diagram-editor
urlParams['sync'] = 'manual';
urlParams['gapi'] = '0';
urlParams['db'] = '0';
urlParams['od'] = '0';
urlParams['tr'] = '0';
urlParams['gh'] = '0';
urlParams['gl'] = '0';
urlParams['ms365'] = '0';
urlParams['picker'] = '0';

(function()
{
    function ensureConstructor(name)
    {
        if (typeof window[name] !== 'function')
        {
            window[name] = function() {};
        }
    }

    [
        'DriveFile',
        'DriveLibrary',
        'DropboxFile',
        'DropboxLibrary',
        'OneDriveFile',
        'OneDriveLibrary',
        'GitHubFile',
        'GitHubLibrary',
        'GitLabFile',
        'GitLabLibrary',
        'TrelloFile',
        'TrelloLibrary'
    ].forEach(ensureConstructor);

    if (typeof window.OneDriveFile.prototype.getIdOf !== 'function')
    {
        window.OneDriveFile.prototype.getIdOf = function(value)
        {
            return value && (value.id || value.driveId || value.name) || '';
        };
    }
})();
