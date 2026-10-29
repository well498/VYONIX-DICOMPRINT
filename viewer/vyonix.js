/**
 * Configuração do OHIF Viewer 3.13 para o VYONIX (BKL-05).
 *
 * O Viewer é servido pelo CORE em /viewer/ (mesma origem): as chamadas DICOMweb levam o cookie da
 * sessão do VYONIX e passam pelo índice da organização (row level security) e pela auditoria.
 * Nenhum servidor DICOMweb externo, nenhuma extensão de terceiros além das padrão do OHIF.
 * Não liberado para uso clínico.
 */
window.config = {
  routerBasename: '/viewer',
  extensions: [],
  modes: [],
  showStudyList: true,
  maxNumberOfWebWorkers: 3,
  showWarningMessageForCrossOrigin: false,
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  strictZSpacingForVolumeViewport: true,
  investigationalUseDialog: { option: 'never' },
  // Sem o tour guiado do primeiro uso (em inglês e sobreposto à imagem). Fase "global" do customizationService
  // do OHIF 3.13: aplicada depois que as extensões registram as personalizações padrão.
  // Identificação do exame em cada quadro (essencial na comparação atual × anterior): o OHIF já mostra a data do
  // estudo e a descrição da série; acrescenta modalidade e descrição do exame. Só personalização (sem código no OHIF).
  customizationService: {
    global: [
      { 'ohif.tours': { $set: [] } },
      {
        'viewportOverlay.topLeft': {
          $push: [
            {
              id: 'VyonixExame',
              inheritsFrom: 'ohif.overlayItem',
              label: '',
              title: 'Exame',
              condition: ({ referenceInstance }) =>
                referenceInstance && (referenceInstance.Modality || referenceInstance.StudyDescription),
              contentF: ({ referenceInstance }) =>
                [referenceInstance.Modality, referenceInstance.StudyDescription].filter(Boolean).join(' · '),
            },
          ],
        },
      },
    ],
  },
  defaultDataSourceName: 'vyonix',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'vyonix',
      configuration: {
        friendlyName: 'VYONIX PACS',
        name: 'VYONIX',
        wadoUriRoot: '/api/v1/pacs/dicomweb',
        qidoRoot: '/api/v1/pacs/dicomweb',
        wadoRoot: '/api/v1/pacs/dicomweb',
        qidoSupportsIncludeField: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        staticWado: false,
        singlepart: false,
        omitQuotationForMultipartRequest: true,
        bulkDataURI: { enabled: false },
      },
    },
  ],
  httpErrorHandler: error => {
    if (error && error.status === 401) {
      window.location.href = '/';
    }
  },
};
