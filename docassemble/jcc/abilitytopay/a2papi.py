import requests
import calendar
import time
import json
import dateutil.parser
import datetime
import hashlib
from docassemble.base.util import *
from azure.storage.blob import BlockBlobService

def fetch_citation_data(citation_number, county):
    citation_params = {
            'num': citation_number,
            'county': county
    }
    res = __do_request(a2p_config()['citation_lookup_url'], citation_params)
    return __format_response(res)

def fetch_case_data(first_name, last_name, dob, drivers_license, county):
    case_params = {
            'firstName': first_name,
            'lastName': last_name,
            'dateOfBirth': "%s/%s/%s" % (dob.month, dob.day, dob.year),
            'driversLicense': drivers_license,
            'county': county
    }
    res = __do_request(a2p_config()['case_lookup_url'], case_params)
    return __format_response(res)

def date_from_iso8601(date_string):
    return dateutil.parser.parse(date_string).date()

def format_money(money_string):
    return '${:,.2f}'.format(money_string)

def __format_response(response, request_body=None):
    response_data = {}
    response_data['response_code'] = response.status_code
    response_data['data'] = response.json()

    # Protect against server response of empty hash
    if response_data['data'] == [{}]:
        response_data['data'] = None

    if response.ok:
        response_data['success'] = True
        response_data['error'] = None

        if request_body:
            response_data['request_body'] = request_body
    else:
        response_data['data'] = None
        response_data['success'] = False
        response_data['error'] = response.text

    return response_data

def __log_response(msg, response):
    lines = []
    lines.append("-----------")
    lines.append("Request URL: %s" % response.request.url)
    lines.append("Request Body: %s" % response.request.body)
    lines.append("Request Headers: %s" % response.request.headers)
    lines.append("Response URL: %s" % response.url)
    lines.append("Response Body: %s" % response.text)
    lines.append("Response Headers: %s" % response.headers)
    lines.append("Response Code: %s" % response.status_code)
    lines.append("-----------")
    log("\n".join(lines))

def __do_request(url, params):
    resource = a2p_config()['oauth_resource']
    oauth_params = {
            'resource': resource,
            'grant_type': 'client_credentials',
            'client_id': a2p_config()["client_id"],
            'client_secret': a2p_config()["client_secret"],
            'scope': 'openid ' + resource
    }
    r = requests.post(a2p_config()["ad_url"], oauth_params)
    data = r.json()
    if 'access_token' not in data:
        __log_response("could not get access token", r)

    access_token = data['access_token']

    headers = { 'Authorization': 'Bearer ' + access_token, 'Content-Type': 'application/json' }
    res = requests.post(url, data=None, json=params, headers=headers)
    __log_response("a2p api request", res)
    return res

def a2p_config():
    cfg = get_config('a2p')
    base_url = cfg['base_url']
    cfg['citation_lookup_url'] = base_url + '/case/citation'
    cfg['case_lookup_url'] = base_url + '/case/cases'
    cfg['submit_url'] = base_url + '/request'
    return cfg

def __submit_image_from_url(url):
    blob_service = BlockBlobService(account_name='a2pca', account_key=a2p_config()['blob_account_key'])
    image_body = requests.get(url).content
    filename = 'a2p_daupload_' + hashlib.sha224(image_body).hexdigest()
    blob_service.create_blob_from_bytes('attachments', filename, image_body)

    return {
            "fileName": filename,
            "blobName": filename,
            "size": len(image_body)
            }

def build_submit_payload(data, attachment_urls):
    benefit_files_data = []

    for url in attachment_urls:
        log("Uploading file: %s" % url)
        image_meta = __submit_image_from_url(url)
        benefit_files_data.append(image_meta)

    proof_fields = [
        'calfresh',
        'medi_cal',
        'ssi',
        'ssp',
        'cr_ga',
        'ihss',
        'tanf'
        'cal_works',
        'capi',
    ]

    no_docs_upload_comments = []
    for field in proof_fields:
        reason = data.get(field + "_no_proof_reason")
        if reason:
            no_docs_upload_comments.append("%s: %s" % (field, reason))

    case_information = data.get('case_information')

    benefits = data.get('benefits', {}).get('elements', {})
    no_benefits = True
    for benefit_name in ['cal_fresh', 'ssi', 'ssp', 'medi_cal', 'cr_ga', 'ihss', 'cal_works', 'tanf', 'capi', 'other']:
        if benefits.get(benefit_name):
            no_benefits = False

    submitted_on = datetime.datetime.now().isoformat()

    on_other_benefits = benefits.get('other', False)
    other_benefits_desc = None
    if on_other_benefits:
        other_benefits_desc = data.get('other_benefits_name')
        no_benefits = False

    violDescriptions = []
    idx = 0
    for charge in case_information.get('charges', {}):
        descr = []
        idx += 1
        descr.append("Count %s" % idx)
        if charge.get('chargeCode'):
            descr.append(charge.get('chargeCode'))
        descr.append(charge.get('violationDescription'))
        violDescriptions.append("-".join(descr))

    additional_requests = data.get('additional_requests', {}).get('elements', {})

    difficultyToVisitCourtDueTo = data.get("difficult_open_text", "")
    for k, v in data.get('why_difficult', {}).get('elements', {}).items():
         if v:
              difficultyToVisitCourtDueTo += "/ " + k

    request_params = {
        "requestStatus": "Submitted",
        "petition": {
            "noBenefits": no_benefits,
            "onFoodStamps": benefits.get('cal_fresh', False),
            "onSuppSecIncome": benefits.get('ssi', False),
            "onSSP": benefits.get('ssp', False),
            "onMedical": benefits.get('medi_cal', False),
            "onCountyRelief": benefits.get('cr_ga', False),
            "onIHSS": benefits.get('ihss', False),
            "onCalWorks": benefits.get('cal_works', False),
            "onTANF": benefits.get('tanf', False),
            "onCAPI": benefits.get('capi', False),
            "benefitFiles": benefit_files_data,
            "rent": data.get('monthly_rent'),
            "mortgage": data.get('mortgage'),
            "phone": data.get('phone_bill'),
            "food": data.get('food'),
            "insurance": data.get('insurance'),
            "isBenefitsProof": len(attachment_urls) > 0,
            "isCivilAssessWaiver": False,
            "clothes": data.get('clothing'),
            "childSpousalSupp": data.get('child_spousal_support'),
            "carPayment": data.get('transportation'),
            "utilities": data.get('utilities'),
            "otherExpenses": [],
            "isMoreTimeToPay": additional_requests.get('extension', False),
            "isPaymentPlan": additional_requests.get('payment_plan', False),
            "isReductionOfPayment": True,
            "isCommunityService": additional_requests.get('community_service', False),
            "isOtherRequest": False,
            "otherRequestDesc": data.get('other_hardship'),
            "selectAllRights": True,
            "representByAttorneyRight": True,
            "speedyTrialRight": True,
            "presentEvidenceRight": True,
            "testifyUnderOathRight": True,
            "remainSilentRight": True,
            "isPleadGuilty": data.get('plea', '') == "agree_guilty",
            "isPleadNoContest": data.get('plea', '') == "agree_no_contest",
            "supportingFiles": [],
            "noDocsToUploadReason": "See comments",
            "noDocsToUploadComments": "\n".join(no_docs_upload_comments),
            "isDeclare": True,
            "onOtherBenefits": on_other_benefits,
            "onOtherBenefitsDesc": other_benefits_desc,
        },
        "caseInformation": {
            "caseNumber": case_information.get('caseNumber'),
            "citationDocumentId": case_information.get('documentid'),
            "citationNumber": case_information.get('citationNumber'),
            "civilAssessFee": case_information.get('civilAssessFee'),
            "county": data.get('county'),
            "fullName": case_information.get('firstName', '') + ' ' + case_information.get('lastName', ''),
            "totalDueAmt": case_information.get('totalDueAmt'),
            "violationDate": case_information.get('charges', [])[0].get('violationDate'),
            "violationDescription": "\n".join(violDescriptions),

        },
        "benefitsStatus": not no_benefits,
        "defendantInformation": {
            "incomeAmount": data.get('income'),
            "incomeFrequency": "Month",
            "totalFamilyMembers": data.get('residents'),
        },
        "survey": {
            "isAddressedTrafficMatter": data.get('tool_helpful', '') + ',' + data.get('tool_difficult', ''),
            "willYouVisitCourt": data.get('prefer'),
            "difficultyToVisitCourtDueTo": difficultyToVisitCourtDueTo,
        },
        "submittedById": "0",
        "judgment": "Submitted",
        "submittedByEmail": data.get('email'),
        "submittedOn": submitted_on,
        "needMoreInformation": [],
        "toolRecommendations": [],
        "judicialOrder": [],
        "auditInformation": [],
        "__v": 0
    }
    return request_params


def submit_interview(data, attachment_urls=[], debug=False):
    params = build_submit_payload(data, attachment_urls)
    log("Submitting Payload: %s" % params)
    res = __do_request(a2p_config()['submit_url'], params)

    if debug:
        return __format_response(res, params)
    else:
        return __format_response(res)


# NOTE: Testing the below functions on local may not work
# due to firewall restrictions.
# 
# print(fetch_citation_data('MCRDINTR180000001001', 'Shasta'))
# print(fetch_case_data('john', 'doe', '11/26/1985', '12345', 'Santa Clara'))
# print(submit_interview({ 'citationNumber': 1234 }))


