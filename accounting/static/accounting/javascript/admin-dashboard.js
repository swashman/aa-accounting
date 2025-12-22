/* global DataTable, fetchGet, urlOutstanding, urlCorpOutstanding, urlUserOutstanding */
$(document).ready(() => {
    'use strict';
    const elementTable = $('#outstanding-table');


    fetchGet({ url: urlOutstanding })
        .then((data) => {
            if (data) {
                const dt = new DataTable(elementTable, { // eslint-disable-line no-unused-vars
                    data: data,
                    ordering: false,
                    searching: false,
                    columns: [
                        {
                            data: 'name',
                            className: 'entry-name',
                            render: function (name, type, row) {
                                let url;

                                if (row.kind === 'corp') {
                                    url = urlCorpOutstanding.replace('0', row.id);
                                } else {
                                    url = urlUserOutstanding.replace('0', row.id);
                                }

                                return `<a href="${url}">${name}</a>`;
                            }
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
                            data: 'days_outstanding',
                            className: 'entry-days'
                        },
                    ],
                    initComplete: () => {
                        elementTable.DataTable();

                    }
                });
            }
        })
        .catch((error) => {
            $('#outstanding-table tbody tr td').html(
                '<p class="text-danger mb-0">Error loading transactions.</p>'
            );
            console.error('Error fetching ledger:', error);
        });

});
