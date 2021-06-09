"""OmicLearn main file."""
import random
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image
import warnings
warnings.simplefilter("ignore", FutureWarning)
import utils.session_states as session_states
from utils.helper import (get_download_link, get_system_report, load_data,
                          objdict, main_components, perform_cross_validation,
                          plot_confusion_matrices, plot_feature_importance,
                          plot_pr_curve_cv, plot_roc_curve_cv,
                          transform_dataset, perform_EDA)

# Set the configs
APP_TITLE = "OmicLearn — ML platform for biomarkers"
st.set_page_config(
    page_title = APP_TITLE, 
    page_icon = Image.open('./utils/omic_learn.ico'), 
    layout = "centered", 
    initial_sidebar_state = "auto")
icon = Image.open('./utils/omic_learn.png')
report = get_system_report()

# Checkpoint for XGBoost
xgboost_installed = False
try:
    import xgboost
    from xgboost import XGBClassifier
    xgboost_installed = True
except ModuleNotFoundError:
    st.warning('**WARNING:** Xgboost not installed. To use xgboost install using `conda install py-xgboost`')

# Show main text and data upload section
def main_text_and_data_upload(state):
    st.title(APP_TITLE)
    st.info("""
        - Upload your excel / csv file here. Maximum size is 200 Mb.
        - Each row corresponds to a sample, each column to a feature.
        - 'Features' such as protein IDs, gene names, lipids or miRNA IDs should be uppercase.
        - Additional features should be marked with a leading '_'.
    """)
    
    with st.beta_expander("Upload or select dataset (*Required)", expanded=True):
        file_buffer = st.file_uploader("Upload your dataset below", type=["csv", "xlsx", "xls"])
        st.markdown("""By uploading a file, you agree that you accepting 
                    [the license agreement](https://github.com/OmicEra/OmicLearn/blob/master/LICENSE).
                    \n\n**Note:** We do not save the data you upload via the file uploader; 
                    it is only stored temporarily in RAM to perform the calculations.""")
        delimiter = st.selectbox("Determine the delimiter in your dataset", ["Excel File", "Comma (,)", "Semicolon (;)"])
        state['sample_file'] = st.selectbox("Or select sample file here:", ["None", "Alzheimer", "Sample"])

        df, warnings = load_data(file_buffer, delimiter)

        for warning in warnings:
            st.warning(warning)
        state['df'] = df

        # Sample dataset / uploaded file selection
        dataframe_length = len(state.df)
        max_df_length = 30

        if state.sample_file != 'None' and dataframe_length:
            st.warning("**WARNING:** Please, either choose a sample file or set it as `None` to work on your file")
            state['df'] = pd.DataFrame()
        elif state.sample_file != 'None':
            if state.sample_file == "Alzheimer":
                st.info("""
                    **This dataset is retrieved from the following paper and the code for parsing is available at
                    [GitHub](https://github.com/OmicEra/OmicLearn/blob/master/data/Alzheimer_paper.ipynb):**\n
                    Bader, J., Geyer, P., Müller, J., Strauss, M., Koch, M., & Leypoldt, F. et al. (2020).
                    Proteome profiling in cerebrospinal fluid reveals novel biomarkers of Alzheimer's disease.
                    Molecular Systems Biology, 16(6). doi: [10.15252/msb.20199356](http://doi.org/10.15252/msb.20199356) 
                    """)
            state['df'] = pd.read_excel('data/' + state.sample_file + '.xlsx')
            st.markdown("Using the following dataset:")
            st.write(state.df.head(max_df_length))
        elif 0 < dataframe_length < max_df_length:
            st.markdown("Using the following dataset:")
            st.write(state.df)
        elif dataframe_length > max_df_length:
            st.markdown("Using the following dataset:")
            st.info(f"The dataframe is too large, displaying the first {max_df_length} rows.")
            st.write(state.df.head(max_df_length))
        else:
            st.warning("**WARNING:** No dataset uploaded or selected.")

    return state

# Choosing sample dataset and data parameter selections
def checkpoint_for_data_upload(state, record_widgets):
    multiselect = record_widgets.multiselect
    state['n_missing'] = state.df.isnull().sum().sum()

    if len(state.df) > 0:
        if state.n_missing > 0:
            st.info(f'**INFO:** Found {state.n_missing} missing values. '
                       'Use missing value imputation or `xgboost` classifier.')
        # Distinguish the features from others
        state['proteins'] = [_ for _ in state.df.columns.to_list() if _[0] != '_']
        state['not_proteins'] = [_ for _ in state.df.columns.to_list() if _[0] == '_']

        # Dataset -- Subset
        with st.beta_expander("Create subset"):
            st.markdown("""
                        This section allows you to specify a subset of data based on values within a comma.
                        Hence, you can exclude data that should not be used at all.""")
            state['subset_column'] = st.selectbox("Select subset column:", ['None'] + state.not_proteins)

            if state.subset_column != 'None':
                subset_options = state.df[state.subset_column].value_counts().index.tolist()
                subset_class = multiselect("Select values to keep:", subset_options, default=subset_options)
                state['df_sub'] = state.df[state.df[state.subset_column].isin(subset_class)].copy()
            elif state.subset_column == 'None':
                state['df_sub'] = state.df.copy()
                state['subset_column'] = 'None'

        # Dataset -- Feature selections
        with st.beta_expander("Classification target (*Required)"):
            state['target_column'] = st.selectbox("Select target column:", [""] + state.not_proteins, 
                                        format_func=lambda x: "Select a classification target" if x == "" else x)
            if state.target_column == "":
                unique_elements_lst = []
            else:
                st.markdown(f"Unique elements in `{state.target_column}` column:")
                unique_elements = state.df_sub[state.target_column].value_counts()
                st.write(unique_elements)
                unique_elements_lst = unique_elements.index.tolist()

        # Dataset -- Class definitions
        with st.beta_expander("Define classes (*Required)"):
            # Dataset -- Define the classes
            st.markdown(f"Define classes in `{state.target_column}` column")
            state['class_0'] = multiselect("Select Class 0:", unique_elements_lst, default=None)
            state['class_1'] = multiselect("Select Class 1:",
                                        [_ for _ in unique_elements_lst if _ not in state.class_0], default=None)
            state['remainder'] = [_ for _ in state.not_proteins if _ is not state.target_column]

        # Once both classes are defined
        if state.class_0 and state.class_1:

            # EDA Part
            with st.beta_expander("EDA — Exploratory data analysis (^ Recommended)"):
                st.markdown("""
                    Exploratory data analysis is performed on the whole dataset for providing more insight.
                    For more information, please visit 
                    [the dedicated Wiki page](https://github.com/OmicEra/OmicLearn/wiki/METHODS-%7C-3.-Exploratory-data-analysis).
                    """)
                state['eda_method'] = st.selectbox("Select an EDA method:", ["None", "PCA", "Hierarchical clustering"])
                state['df_sub_y'] = state.df_sub[state.target_column].isin(state.class_0)
                
                if (state.eda_method != "None") and (st.button('Perform EDA', key='run')):
                    p = perform_EDA(state)
                    if state.eda_method == "PCA":
                        st.plotly_chart(p, use_container_width=True)
                        get_download_link(p, "pca.pdf")
                        get_download_link(p, "pca.svg")
                    elif state.eda_method == "Hierarchical clustering":
                        st.plotly_chart(p, use_container_width=True)
                        get_download_link(p, "Hierarchical_clustering.pdf")
                        get_download_link(p, "Hierarchical_clustering.svg")

            with st.beta_expander("Additional features"):
                st.markdown("Select additional features. All non numerical values will be encoded (e.g. M/F -> 0,1)")
                state['additional_features'] = multiselect("Select additional features for trainig:", state.remainder, default=None)

            # Exclude features
            with st.beta_expander("Exclude features"):
                state['exclude_features'] = []
                st.markdown("Exclude some features from the model training by selecting or uploading a CSV file")
                # File uploading target_column for exclusion
                exclusion_file_buffer = st.file_uploader("Upload your CSV (comma(,) seperated) file here in which each row corresponds to a feature to be excluded.", type=["csv"])
                exclusion_df, exc_df_warnings = load_data(exclusion_file_buffer, "Comma (,)")
                for warning in exc_df_warnings:
                    st.warning(warning)

                if len(exclusion_df) > 0:
                    st.markdown("The following features will be excluded:")
                    st.write(exclusion_df)
                    exclusion_df_list = list(exclusion_df.iloc[:, 0].unique())
                    state['exclude_features'] = multiselect("Select features to be excluded:",
                                                    state.proteins, default=exclusion_df_list)
                else:
                    state['exclude_features'] = multiselect("Select features to be excluded:",
                                                                state.proteins, default=[])
            
            # Manual feature selection
            with st.beta_expander("Manually select features"):
                st.markdown("Manually select a subset of features. If only these features should be used, also set the "
                            "`Feature selection` method to `None`. Otherwise feature selection will be applied.")
                manual_users_features = multiselect("Select your features manually:", state.proteins, default=None)
            if manual_users_features:
                state.proteins = manual_users_features

        # Dataset -- Cohort selections
        with st.beta_expander("Cohort comparison"):
            st.markdown('Select cohort column to train on one and predict on another:')
            not_proteins_excluded_target_option = state.not_proteins
            if state.target_column != "":
                not_proteins_excluded_target_option.remove(state.target_column)
            state['cohort_column'] = st.selectbox("Select cohort column:", [None] + not_proteins_excluded_target_option)
            if state['cohort_column'] == None:
                state['cohort_checkbox'] = None
            else:
                state['cohort_checkbox'] = "Yes"

            if 'exclude_features' not in state:
                state['exclude_features'] = []

        state['proteins'] = [_ for _ in state.proteins if _ not in state.exclude_features]

    return state

# Generate sidebar elements
def generate_sidebar_elements(state, record_widgets):
    slider_ = record_widgets.slider_
    selectbox_ = record_widgets.selectbox_
    number_input_ = record_widgets.number_input_

    # Sidebar -- Image/Title
    st.sidebar.image(icon, use_column_width=True, caption="OmicLearn " + report['omic_learn_version'])
    st.sidebar.markdown("# [Options](https://github.com/OmicEra/OmicLearn/wiki/METHODS)")

    # Sidebar -- Random State
    state['random_state'] = slider_(
        "Random State:", min_value=0, max_value=99, value=23)

    # Sidebar -- Preprocessing
    st.sidebar.markdown('## [Preprocessing](https://github.com/OmicEra/OmicLearn/wiki/METHODS-%7C-1.-Preprocessing)')
    normalizations = ['None', 'StandardScaler', 'MinMaxScaler', 'RobustScaler', 'PowerTransformer', 'QuantileTransformer']
    state['normalization'] = selectbox_("Normalization method:", normalizations)

    normalization_params = {}

    if state.normalization == "PowerTransformer":
        normalization_params['method'] = selectbox_("Power transformation method:", ["Yeo-Johnson", "Box-Cox"]).lower()
    elif state.normalization == "QuantileTransformer":
        normalization_params['random_state'] = state.random_state
        normalization_params['n_quantiles'] = number_input_(
            "Number of quantiles:", value=100, min_value=1, max_value=2000)
        normalization_params['output_distribution'] = selectbox_("Output distribution method:", ["Uniform", "Normal"]).lower()
    if state.n_missing > 0:
        st.sidebar.markdown('## [Missing value imputation](https://github.com/OmicEra/OmicLearn/wiki/METHODS-%7C-1.-Preprocessing#1-2-imputation-of-missing-values)')
        missing_values = ['Zero', 'Mean', 'Median', 'KNNImputer', 'None']
        state['missing_value'] = selectbox_("Missing value imputation", missing_values)
    else:
        state['missing_value'] = 'None'

    state['normalization_params'] = normalization_params

    # Sidebar -- Feature Selection
    st.sidebar.markdown('## [Feature selection](https://github.com/OmicEra/OmicLearn/wiki/METHODS-%7C-2.-Feature-selection)')
    feature_methods = ['ExtraTrees', 'k-best (mutual_info_classif)', 'k-best (f_classif)', 'k-best (chi2)', 'None']
    state['feature_method'] = selectbox_("Feature selection method:", feature_methods)

    if state.feature_method != 'None':
        state['max_features'] = number_input_('Maximum number of features:',
                                              value=20, min_value=1,
                                              max_value=2000)
    else:
        # Define `max_features` as 0 if `feature_method` is `None`
        state['max_features'] = 0

    if state.feature_method == "ExtraTrees":
        state['n_trees'] = number_input_('Number of trees in the forest:',
                                         value=100, min_value=1,
                                         max_value=2000)
    else:
        state['n_trees'] = 0

    # Sidebar -- Classification method selection
    st.sidebar.markdown('## [Classification](https://github.com/OmicEra/OmicLearn/wiki/METHODS-%7C-4.-Classification#3-classification)')
    classifiers = ['AdaBoost', 'LogisticRegression', 'KNeighborsClassifier',
                   'RandomForest', 'DecisionTree', 'LinearSVC']
    if xgboost_installed:
        classifiers += ['XGBoost']

    # Disable all other classification methods
    if (state.n_missing > 0) and (state.missing_value == 'None'):
        classifiers = ['XGBoost']

    state['classifier'] = selectbox_("Specify the classifier:", classifiers)
    classifier_params = {}
    classifier_params['random_state'] = state['random_state']

    if state.classifier == 'AdaBoost':
        classifier_params['n_estimators'] = number_input_('Number of estimators:', value=100, min_value=1, max_value=2000)
        classifier_params['learning_rate'] = number_input_('Learning rate:', value=1.0, min_value=0.001, max_value=100.0)

    elif state.classifier == 'KNeighborsClassifier':
        classifier_params['n_neighbors'] = number_input_('Number of neighbors:', value=100, min_value=1, max_value=2000)
        classifier_params['weights'] = selectbox_("Select weight function used:", ["uniform", "distance"])
        classifier_params['algorithm'] = selectbox_("Algorithm for computing the neighbors:", ["auto", "ball_tree", "kd_tree", "brute"])

    elif state.classifier == 'LogisticRegression':
        classifier_params['penalty'] = selectbox_("Specify norm in the penalization:", ["l2", "l1", "ElasticNet", "None"]).lower()
        classifier_params['solver'] = selectbox_("Select the algorithm for optimization:", ["lbfgs", "newton-cg", "liblinear", "sag", "saga"])
        classifier_params['max_iter'] = number_input_('Maximum number of iteration:', value=100, min_value=1, max_value=2000)
        classifier_params['C'] = number_input_('C parameter:', value=1, min_value=1, max_value=100)

    elif state.classifier == 'RandomForest':
        classifier_params['n_estimators'] = number_input_('Number of estimators:', value=100, min_value=1, max_value=2000)
        classifier_params['criterion'] = selectbox_("Function for measure the quality:", ["gini", "entropy"])
        classifier_params['max_features'] = selectbox_("Number of max. features:", ["auto", "int", "sqrt", "log2"])
        if classifier_params['max_features'] == "int":
            classifier_params['max_features'] = number_input_('Number of max. features:', value=5, min_value=1, max_value=100)

    elif state.classifier == 'DecisionTree':
        classifier_params['criterion'] = selectbox_("Function for measure the quality:", ["gini", "entropy"])
        classifier_params['max_features'] = selectbox_("Number of max. features:", ["auto", "int", "sqrt", "log2"])
        if classifier_params['max_features'] == "int":
            classifier_params['max_features'] = number_input_('Number of max. features:', value=5, min_value=1, max_value=100)

    elif state.classifier == 'LinearSVC':
        classifier_params['penalty'] = selectbox_("Specify norm in the penalization:", ["l2", "l1"])
        classifier_params['loss'] = selectbox_("Select loss function:", ["squared_hinge", "hinge"])
        classifier_params['C'] = number_input_('C parameter:', value=1, min_value=1, max_value=100)
        classifier_params['cv_generator'] = number_input_('Cross-validation generator:', value=2, min_value=2, max_value=100)

    elif state.classifier == 'XGBoost':
        classifier_params['learning_rate'] = number_input_('Learning rate:', value=0.3, min_value=0.0, max_value=1.0)
        classifier_params['min_split_loss'] = number_input_('Min. split loss:', value=0, min_value=0, max_value=100)
        classifier_params['max_depth'] = number_input_('Max. depth:', value=6, min_value=0, max_value=100)
        classifier_params['min_child_weight'] = number_input_('Min. child weight:', value=1, min_value=0, max_value=100)

    state['classifier_params'] = classifier_params

    # Sidebar -- Cross-Validation
    st.sidebar.markdown('## [Cross-validation](https://github.com/OmicEra/OmicLearn/wiki/METHODS-%7C-5.-Validation#4-1-cross-validation)')
    state['cv_method'] = selectbox_("Specify CV method:", ["RepeatedStratifiedKFold", "StratifiedKFold", "StratifiedShuffleSplit"])
    state['cv_splits'] = number_input_('CV Splits:', min_value=2, max_value=10, value=5)

    # Define placeholder variables for CV
    if state.cv_method == 'RepeatedStratifiedKFold':
        state['cv_repeats'] = number_input_('CV Repeats:', min_value=1, max_value=50, value=10)

    return state

# Display results and plots
def classify_and_plot(state):

    state.bar = st.progress(0)
    # Cross-Validation
    st.markdown("Performing analysis and Running cross-validation")
    cv_results, cv_curves = perform_cross_validation(state)

    st.header('Cross-validation results')
    # Feature importances from the classifier
    with st.beta_expander("Feature importances from the classifier"):
        st.subheader('Feature importances from the classifier')
        if state.cv_method == 'RepeatedStratifiedKFold':
            st.markdown(f'This is the average feature importance from all {state.cv_splits*state.cv_repeats} cross validation runs.')
        else:
            st.markdown(f'This is the average feature importance from all {state.cv_splits} cross validation runs.')
        if cv_curves['feature_importances_'] is not None:

            # Check whether all feature importance attributes are 0 or not
            if pd.DataFrame(cv_curves['feature_importances_']).isin([0]).all().all() == False:
                p, feature_df, feature_df_wo_links = plot_feature_importance(cv_curves['feature_importances_'])
                st.plotly_chart(p, use_container_width=True)
                if p:
                    get_download_link(p, 'clf_feature_importance.pdf')
                    get_download_link(p, 'clf_feature_importance.svg')

                # Display `feature_df` with NCBI links
                st.subheader("Feature importances from classifier table")
                st.write(feature_df.to_html(escape=False, index=False), unsafe_allow_html=True)
                get_download_link(feature_df_wo_links, 'clf_feature_importances.csv')
            else:
                st.info("All feature importance attribute as zero (0). Hence, the plot and table are not displayed.")
        else:
            st.info('Feature importance attribute is not implemented for this classifier.')

    # ROC-AUC
    with st.beta_expander("Receiver operating characteristic Curve and Precision-Recall Curve"):
        st.subheader('Receiver operating characteristic')
        p = plot_roc_curve_cv(cv_curves['roc_curves_'])
        st.plotly_chart(p, use_container_width=True)
        if p:
            get_download_link(p, 'roc_curve.pdf')
            get_download_link(p, 'roc_curve.svg')

        # Precision-Recall Curve
        st.subheader('Precision-Recall Curve')
        st.markdown("Precision-Recall (PR) Curve might be used for imbalanced datasets.")
        p = plot_pr_curve_cv(cv_curves['pr_curves_'], cv_results['class_ratio_test'])
        st.plotly_chart(p, use_container_width=True)
        if p:
            get_download_link(p, 'pr_curve.pdf')
            get_download_link(p, 'pr_curve.svg')

    # Confusion Matrix (CM)
    with st.beta_expander("Confusion matrix"):
        st.subheader('Confusion matrix')
        names = ['CV_split {}'.format(_+1) for _ in range(len(cv_curves['y_hats_']))]
        names.insert(0, 'Sum of all splits')
        p = plot_confusion_matrices(state.class_0, state.class_1, cv_curves['y_hats_'], names)
        st.plotly_chart(p, use_container_width=True)
        if p:
            get_download_link(p, 'cm.pdf')
            get_download_link(p, 'cm.svg')

    # Results table
    with st.beta_expander("Table for run results"):
        st.subheader(f'Run results for `{state.classifier}`')
        state['summary'] = pd.DataFrame(pd.DataFrame(cv_results).describe())
        st.write(state.summary)
        get_download_link(state.summary, "run_results.csv")

    if state.cohort_checkbox:
        st.header('Cohort comparison results')
        cohort_results, cohort_curves = perform_cross_validation(state, state.cohort_column)

        with st.beta_expander("Receiver operating characteristic Curve and Precision-Recall Curve"):
            # ROC-AUC for Cohorts
            st.subheader('Receiver operating characteristic')
            p = plot_roc_curve_cv(cohort_curves['roc_curves_'], cohort_curves['cohort_combos'])
            st.plotly_chart(p, use_container_width=True)
            if p:
                get_download_link(p, 'roc_curve_cohort.pdf')
                get_download_link(p, 'roc_curve_cohort.svg')

            # PR Curve for Cohorts
            st.subheader('Precision-Recall Curve')
            st.markdown("Precision-Recall (PR) Curve might be used for imbalanced datasets.")
            p = plot_pr_curve_cv(cohort_curves['pr_curves_'], cohort_results['class_ratio_test'], cohort_curves['cohort_combos'])
            st.plotly_chart(p, use_container_width=True)
            if p:
                get_download_link(p, 'pr_curve_cohort.pdf')
                get_download_link(p, 'pr_curve_cohort.svg')

        # Confusion Matrix (CM) for Cohorts
        with st.beta_expander("Confusion matrix"):
            st.subheader('Confusion matrix')
            names = ['Train on {}, Test on {}'.format(_[0], _[1]) for _ in cohort_curves['cohort_combos']]
            names.insert(0, 'Sum of cohort comparisons')

            p = plot_confusion_matrices(state.class_0, state.class_1, cohort_curves['y_hats_'], names)
            st.plotly_chart(p, use_container_width=True)
            if p:
                get_download_link(p, 'cm_cohorts.pdf')
                get_download_link(p, 'cm_cohorts.svg')

        with st.beta_expander("Table for run results"):
            state['cohort_summary'] = pd.DataFrame(pd.DataFrame(cv_results).describe())
            st.write(state.cohort_summary)
            get_download_link(state.cohort_summary, "run_results_cohort.csv")

        state['cohort_combos'] = cohort_curves['cohort_combos']
        state['cohort_results'] = cohort_results

    return state

# Generate summary text
def generate_text(state):

    text = ""
    # Packages
    packages_plain_text = """
        OmicLearn ({omic_learn_version}) was utilized for performing the data analysis, model execution, and generating the plots and charts.
        Machine learning was done in Python ({python_version}). Feature tables were imported via the Pandas package ({pandas_version}) and manipulated using the Numpy package ({numpy_version}).
        The machine learning pipeline was employed using the scikit-learn package ({sklearn_version}).
        For generating the plots and charts, Plotly ({plotly_version}) library was used.
    """
    text += packages_plain_text.format(**report)

    # Normalization
    if state.normalization == 'None':
        text += 'No normalization on the data was performed. '
    elif state.normalization in ['StandardScaler', 'MinMaxScaler', 'RobustScaler']:
        text += f"Data was normalized in each using a {state.normalization} approach. "
    else:
        params = [f'{k} = {v}' for k, v in state.normalization_params.items()]
        text += f"Data was normalized in each using a {state.normalization} ({' '.join(params)}) approach. "

    # Missing value impt.
    if state.missing_value != "None":
        text += 'To impute missing values, a {}-imputation strategy is used. '.format(state.missing_value)
    else:
        text += 'The dataset contained no missing values; hence no imputation was performed. '

    # Features
    if state.feature_method == 'None':
        text += 'No feature selection algorithm was applied. '
    elif state.feature_method == 'ExtraTrees':
        text += 'Features were selected using a {} (n_trees={}) strategy with the maximum number of {} features. '.format(state.feature_method, state.n_trees, state.max_features)
    else:
        text += 'Features were selected using a {} strategy with the maximum number of {} features. '.format(state.feature_method, state.max_features)
    text += 'Normalization and feature selection was individually performed using the training data of each split. '

    # Classification
    params = [f'{k} = {v}' for k, v in state.classifier_params.items()]
    text += f"For classification, we used a {state.classifier}-Classifier ({' '.join(params)}). "

    # Cross-Validation
    if state.cv_method == 'RepeatedStratifiedKFold':
        cv_plain_text = """
            When using (RepeatedStratifiedKFold) a repeated (n_repeats={}), stratified cross-validation (n_splits={}) approach to classify {} vs. {},
            we achieved a receiver operating characteristic (ROC) with an average AUC (area under the curve) of {:.2f} ({:.2f} std)
            and precision-recall (PR) Curve with an average AUC of {:.2f} ({:.2f} std).
        """
        text += cv_plain_text.format(state.cv_repeats, state.cv_splits, ''.join(state.class_0), ''.join(state.class_1),
                                     state.summary.loc['mean']['roc_auc'], state.summary.loc['std']['roc_auc'], state.summary.loc['mean']['pr_auc'], state.summary.loc['std']['pr_auc'])
    else:
        cv_plain_text = """
            When using {} cross-validation approach (n_splits={}) to classify {} vs. {}, we achieved a receiver operating characteristic (ROC)
            with an average AUC (area under the curve) of {:.2f} ({:.2f} std) and Precision-Recall (PR) Curve with an average AUC of {:.2f} ({:.2f} std).
        """
        text += cv_plain_text.format(state.cv_method, state.cv_splits, ''.join(state.class_0), ''.join(state.class_1),
                                     state.summary.loc['mean']['roc_auc'], state.summary.loc['std']['roc_auc'], state.summary.loc['mean']['pr_auc'], state.summary.loc['std']['pr_auc'])

    if state.cohort_column is not None:
        text += 'When training on one cohort and predicting on another to classify {} vs. {}, we achieved the following AUCs: '.format(''.join(state.class_0), ''.join(state.class_1))
        for i, cohort_combo in enumerate(state.cohort_combos):
            text += '{:.2f} when training on {} and predicting on {} '.format(state.cohort_results['roc_auc'][i], cohort_combo[0], cohort_combo[1])
            text += ', and {:.2f} for PR Curve when training on {} and predicting on {}. '.format(state.cohort_results['pr_auc'][i], cohort_combo[0], cohort_combo[1])

    # Print the all text
    st.header("Summary")
    with st.beta_expander("Summary text"):
        st.info(text)

# Create new list and dict for sessions
@st.cache(allow_output_mutation=True)
def get_sessions():
    return [], {}

# Saving session info
def save_sessions(widget_values, user_name):

    session_no, session_dict = get_sessions()
    session_no.append(len(session_no) + 1)
    session_dict[session_no[-1]] = widget_values
    sessions_df = pd.DataFrame(session_dict)
    sessions_df = sessions_df.T
    sessions_df = sessions_df.drop(sessions_df[sessions_df["user"] != user_name].index).reset_index(drop=True)
    new_column_names = {k:v.replace(":", "").replace("Select", "") for k, v in zip(sessions_df.columns, sessions_df.columns)}
    sessions_df = sessions_df.rename(columns=new_column_names)
    sessions_df = sessions_df.drop("user", axis=1)

    st.write("## Session History")
    st.dataframe(sessions_df.T.style.set_precision(4)) # Display only 3 decimal points in UI side
    get_download_link(sessions_df, "session_history.csv")

# Generate footer
def generate_footer_parts():

    # Citations
    citations = """
        <br> <b>APA Format:</b> <br>
        Torun FM, Virreira Winter S, Doll S, Riese FM, Vorobyev A, Mueller-Reif JB, Geyer PE, Strauss MT (2021).
        Transparent exploration of machine learning for biomarker discovery from proteomics and omics data. doi: <a href="https://doi.org/10.1101/2021.03.05.434053" target="_blank">10.1101/2021.03.05.434053</a>.
    """

    # Put the footer with tabs
    footer_parts_html = """
        <div class="tabs">
            <div class="tab"> <input type="radio" id="tab-1" name="tab-group-1" checked> <label for="tab-1">Citations</label> <div class="content"> <p> {} </p> </div> </div>
            <div class="tab"> <input type="radio" id="tab-2" name="tab-group-1"> <label for="tab-2">Report bugs</label> <div class="content">
                <p><br>
                    We appreciate all contributions. 👍 <br>
                    You can report the bugs or request a feature using the link below or sending us an e-mail:
                    <br><br>
                    <a class="download_link" href="https://github.com/OmicEra/OmicLearn/issues/new/choose" target="_blank">Report a bug via GitHub</a>
                    <a class="download_link" href="mailto:info@omicera.com">Report a bug via Email</a>
                </p>
            </div> </div>
        </div>

        <div class="footer">
            <i> OmicLearn {} </i> <br> <img src="https://omicera.com/wp-content/uploads/2020/05/cropped-oe-favicon-32x32.jpg" alt="OmicEra Diagnostics GmbH">
            <a href="https://omicera.com" target="_blank">OmicEra</a>.
        </div>
        """.format(citations, report['omic_learn_version'])

    st.write("## Cite us & Report bugs")
    st.markdown(footer_parts_html, unsafe_allow_html=True)

# Main Function
def OmicLearn_Main():

    state = objdict()

    state['df'] = pd.DataFrame()
    state['class_0'] = None
    state['class_1'] = None

    # Main components
    widget_values, record_widgets = main_components()

    # Welcome text and Data uploading
    state = main_text_and_data_upload(state)

    # Checkpoint for whether data uploaded/selected
    state = checkpoint_for_data_upload(state, record_widgets)

    # Sidebar widgets
    state = generate_sidebar_elements(state, record_widgets)

    # Analysis Part
    if len(state.df) > 0 and state.target_column == "":
        st.warning('**WARNING:** Select classification target from your data.')

    elif len(state.df) > 0 and not (state.class_0 and state.class_1):
        st.warning('**WARNING:** Define classes for the classification target.')

    elif (state.df is not None) and (state.class_0 and state.class_1) and (st.button('Run analysis', key='run')):
        state.features = state.proteins + state.additional_features
        subset = state.df_sub[state.df_sub[state.target_column].isin(state.class_0) | state.df_sub[state.target_column].isin(state.class_1)].copy()
        state.y = subset[state.target_column].isin(state.class_0)
        state.X = transform_dataset(subset, state.additional_features, state.proteins)

        if state.cohort_column is not None:
            state['X_cohort'] = subset[state.cohort_column]
        
        # Show the running info text
        st.info(f"""
            **Running info:**
            - Using the following features: **Class 0 `{state.class_0}`, Class 1 `{state.class_1}`**.
            - Using classifier **`{state.classifier}`**.
            - Using a total of  **`{len(state.features)}`** features.
            - Note that OmicLearn is intended to be an exploratory tool to assess the performance of algorithms, 
                rather than a classification model for production. 
        """)

        # Plotting and Get the results
        state = classify_and_plot(state)

        # Generate summary text
        generate_text(state)

        # Session and Run info
        widget_values["Date"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " (UTC)"

        for _ in state.summary.columns:
            widget_values[_+'_mean'] = state.summary.loc['mean'][_]
            widget_values[_+'_std'] = state.summary.loc['std'][_]

        user_name = str(random.randint(0, 10000)) + "OmicLearn"
        session_state = session_states.get(user_name=user_name)
        widget_values["user"] = session_state.user_name
        save_sessions(widget_values, session_state.user_name)

        # Generate footer
        generate_footer_parts()

    else:
        pass

# Run the OmicLearn
if __name__ == '__main__':
    try:
        OmicLearn_Main()
    except (ValueError, IndexError) as val_ind_error:
        st.error(f"There is a problem with values/parameters or dataset due to {val_ind_error}.")
    except TypeError as e:
        # st.warning("TypeError exists in {}".format(e))
        pass
