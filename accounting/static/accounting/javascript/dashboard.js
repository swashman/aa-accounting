/* global DataTable, fetchGet, moment, urlLedger */
$(document).ready(() => {
    'use strict';

    const elementTable = $('#ledger-table');


    fetchGet({ url: urlLedger })
        .then((data) => {
            if (data) {
                const dt = new DataTable(elementTable, { // eslint-disable-line no-unused-vars
                    data: data,
                    ordering: false,
                    searching: false,
                    columns: [
                        {
                            data: {
                                display: (data) => data.created === null ? '' : moment(data.created).utc().format('LL<br>LT'),
                                sort: (data) => data.created === null ? '' : data.created

                            },
                            className: 'entry-time'
                        },
                        {
                            data: 'entry_type',
                            className: 'entry-type'
                        },
                        {
                            data: 'amount',
                            className: 'entry-amount',
                            render: function (data) {
                                if (data == null) return '';
                                return parseFloat(data).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
                            }
                        },
                        {
                            data: 'balance',
                            className: 'entry-balance',
                            render: function (data) {
                                if (data == null) return '';
                                return parseFloat(data).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
                            }
                        },
                        {
                            data: 'description',
                            className: 'entry-description',
                            //we chunk the data and use a modal if its long, just for some sanity here
                            render: function (data) {
                                if (!data) return '';

                                const chunkSize = 75; // adjust preview length

                                // Escape HTML
                                const escapeHtml = (text) =>
                                    text.replace(/[&<>"'`]/g, (match) => ({
                                        '&': '&amp;',
                                        '<': '&lt;',
                                        '>': '&gt;',
                                        '"': '&quot;',
                                        "'": '&#39;',
                                        '`': '&#96;'
                                    }[match]));

                                // Preserve newlines as <br>
                                const escapedWithNewlines = escapeHtml(data).replace(/\n/g, '<br>');

                                if (data.length <= chunkSize) {
                                    // Short/medium text — show full multi-line in table cell
                                    return `<span style="color:white; cursor: default;">${escapedWithNewlines}</span>`;
                                } else {
                                    // Long text — truncated preview with ... and click hint
                                    const previewText = escapeHtml(data.slice(0, chunkSize)).replace(/\n/g, '<br>');

                                    return `<span class=""
                                                style="cursor:pointer;"
                                                data-bs-toggle="modal"
                                                data-bs-target="#descriptionModal"
                                                data-fulltext="${escapedWithNewlines}">
                                                ${previewText}… <small>(click to expand)</small>
                                            </span>`;
                                }
                            }
                        },
                    ],
                    initComplete: () => {
                        elementTable.DataTable();

                    }
                });
            }
        })
        .catch((error) => {
            $('#ledger-table tbody tr td').html(
                '<p class="text-danger mb-0">Error loading transactions.</p>'
            );
            console.error('Error fetching ledger:', error);
        });

    const modal = document.getElementById('descriptionModal');

    modal.addEventListener('show.bs.modal', function (event) {
        const trigger = event.relatedTarget;
        const fullText = trigger.getAttribute('data-fulltext');

        // Replace \n with <br> to preserve newlines
        modal.querySelector('.modal-body').innerHTML = fullText.replace(/\n/g, '<br>');
    });
});
